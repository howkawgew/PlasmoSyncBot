"""Main sync cog"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Union, Tuple, List, Any

import aiohttp
import disnake
from aiohttp import ClientSession
from disnake.ext import commands

import plasmosync.utils
from plasmosync import settings
from plasmosync.utils import get_roles_difference, get_guild_switches, is_guild_verified

logger = logging.getLogger(__name__)


class SyncCore(commands.Cog):
    """
    Main cog for user synchronization
    """

    def __init__(self, bot: disnake.ext.commands.Bot) -> None:
        self.bot = bot

    async def _sync_nicknames(
        self, user: disnake.Member
    ) -> tuple[bool, list[Any]] | tuple[bool, list[str]]:
        donor_guild = self.bot.get_guild(settings.DONOR.guild_discord_id)
        nickname = donor_guild.get_member(user.id).display_name
        try:
            await user.edit(
                nick=nickname,
                reason="Nicknames sync is enabled," " use /settings to disable",
            )
            return True, []
        except disnake.Forbidden as error:
            logger.warning(
                "Unable to update %s local nickname at %s, error \n %s",
                user,
                user.guild,
                error,
            )
            return False, [f"Не удалось сменить ник ({user})"]

    async def _sync_roles(
        self, user: disnake.Member
    ) -> tuple[bool, list[Any]] | tuple[bool, list[str]]:
        donor_guild = self.bot.get_guild(settings.DONOR.guild_discord_id)
        donor_user = donor_guild.get_member(user.id)
        if donor_user is None:
            roles_to_remove = [
                donor_guild.get_role(role_id)
                for role_id in (
                    await plasmosync.utils.get_guild_roles(user.id)
                ).values()
            ]
            roles_to_add = []

        else:
            roles_to_add, roles_to_remove = await get_roles_difference(
                donor=settings.DONOR,
                user=user,
                donor_user=donor_user,
            )

        try:
            await user.add_roles(
                *roles_to_add,
                reason="Roles sync is enabled, use /settings to disable",
            )
            await user.remove_roles(
                *roles_to_remove,
                reason="Roles sync is enabled, use /settings to disable",
            )
            return True, []
        except disnake.Forbidden as error:
            logger.warning(error)
            return False, [f"Не удалось снять/добавить роли ({user})"]

    async def _sync_bans(
        self,
        user: Union[disnake.Member, disnake.Object],
        user_guild: Optional[disnake.Guild] = None,
    ) -> tuple[bool, list[Any]] | tuple[bool, list[str]]:
        """
        :param user: User to sync, might be disnake.Object, bc we can't get Member object when user is banned
        :param user_guild: way to hand over user_guild argument, used only if user is disnake.Object
        :return: sync status (False if there were some errors)
        """

        user_guild = user.guild if user_guild is None else user_guild
        donor_guild = self.bot.get_guild(settings.DONOR.guild_discord_id)

        async for ban in donor_guild.bans():
            if ban.user.id == user.id:
                try:
                    await user.ban(
                        delete_message_days=0,
                        reason="Sync bans (privileged) is enabled,"
                        f" use /setting to disable [Plasmo ban reason:  {ban.reason}]",
                    )
                    return True, []
                except disnake.Forbidden as error:
                    logger.warning(
                        "Unable to ban %s in %s, error \n %s",
                        user,
                        user_guild,
                        error,
                    )
                    return False, [f"Не удалось забанить пользователя ({user})"]
        else:
            # If user is banned
            if user_guild.get_member(user.id) is None:
                try:
                    await donor_guild.unban(
                        user,
                        reason="Sync bans (privileged) is enabled,"
                        " use /settings to disable",
                    )
                    return True, []
                except disnake.Forbidden as error:
                    logger.warning(
                        "Unable to unban %s in %s, error \n %s",
                        user,
                        user_guild,
                        error,
                    )
                    return False, [f"Не удалось разбанить пользователя ({user})"]
        return True, []

    async def _api_sync(
        self, user: disnake.Member, guild_settings: Dict[str, bool]
    ) -> tuple[bool, list[Any]] | bool:
        # We already know that guild is verified, so there is no reason to check it again
        donor = settings.DONOR
        guild = user.guild
        sync_status = True
        sync_errors = []

        if donor.api_base_url is None:
            return False, []

        # We know that sync nicknames or sync roles is enabled, so we must do an api call before config checks
        async with ClientSession() as session:
            async with session.get(
                url=f"https://rp.plo.su/api/user/profile?discord_id={user.id}",
            ) as response:
                try:
                    response_json = await response.json()
                except aiohttp.ContentTypeError:
                    return False, ["Не удалось подключиться к Plasmo API"]

                if (
                    response.status != 200
                    or response_json.get("status", False) is False
                    or (userdata := response_json.get("data", None)) is None
                ):
                    logger.warning(
                        "Could not get data from PRP API: %s",
                        response_json,
                    )
                    return False, ["Не удалось подключиться к Plasmo API"]

        userdata: Dict = response_json.get("data")

        username: str = userdata.get("nick", None)
        # is_banned: bool = userdata.get("banned", False)
        # ban_reason: str = userdata.get("ban_reason", "Not specified")

        if (
            guild_settings.get(
                "sync_nicknames",
                False,
            )
            and username is not None
        ):
            try:
                await user.edit(
                    nick=username,
                    reason="Nicknames sync and API are enabled,"
                    " use /settings to disable",
                )
            except disnake.Forbidden:
                sync_status = False
                sync_errors.append(f"[API] Не удалось сменить ник ({user})")

        # TODO: Ban role?
        return sync_status, sync_errors

    async def sync(
        self,
        user: Union[disnake.Member, disnake.Object],
        user_guild: Optional[disnake.Guild] = None,
    ) -> tuple[bool, list[str]] | tuple[bool, list[Any]]:
        """
        Sync user
        :param user: User to sync
        :param user_guild: Guild

        :return: True if successfully synced, False if there were errors during syncing

        """
        if isinstance(user, disnake.Member) and user.bot:
            return True, []

        donor_config = settings.DONOR
        if user_guild is None:
            user_guild = user.guild

        logger.info("Syncing %s at %s", user, user_guild)

        sync_status = True
        sync_errors = []
        # Checks if user_guild is verified
        guild_is_verified: bool = await is_guild_verified(user_guild.id)
        # Get current user_guild settings, donor user_guild and member object from donor
        guild_settings: Dict[str, bool] = await get_guild_switches(user_guild.id)
        donor_guild = self.bot.get_guild(donor_config.guild_discord_id)
        donor_user: Optional[disnake.Member] = donor_guild.get_member(user.id)

        if guild_is_verified:
            user_not_in_guild = user_guild.get_member(user.id) is None

            # Whitelist
            conditions = [
                not user_not_in_guild,
                guild_settings.get("whitelist", False),
                (
                    donor_user is None
                    or donor_config.player_role.discord_id
                    not in [role.id for role in donor_user.roles]
                ),
            ]
            if all(conditions):
                try:
                    await user.kick(
                        reason="Whitelist is enabled, use /settings to disable"
                    )
                except disnake.Forbidden as error:
                    logger.warning(
                        "Could not kick user %s from %s because of \n %s",
                        user,
                        user.guild,
                        error,
                    )
                    sync_status = False
                    sync_errors.append(f"Не удалось кикнуть пользователя ({user})")
                    # TODO: Log that into dev-error-channel

            # Bans
            if user_not_in_guild or guild_settings.get(
                "sync_bans",
                False,
            ):
                status, errors = await self._sync_bans(user=user, user_guild=user_guild)

                sync_errors += errors
                sync_status = False if status is False else sync_status

                if user_not_in_guild:
                    return sync_status, sync_errors

        if donor_user is not None:
            #   Sync roles
            if guild_settings.get("sync_roles", False):
                status, errors = await self._sync_roles(user)
                sync_status = False if status is False else sync_status

                sync_errors += errors

            # sync nicknames
            if guild_settings.get(
                "sync_nicknames",
                False,
            ):
                status, errors = await self._sync_nicknames(user)
                sync_errors += errors
                sync_status = False if status is False else sync_status

        if guild_is_verified:
            if guild_settings.get(
                "sync_bans",
                False,
            ):
                status, errors = await self._sync_bans(user=user, user_guild=user_guild)
                sync_errors += errors
                sync_status = False if status is False else sync_status

            if guild_settings.get(
                "use_api",
                False,
            ):
                status, api_errors = await self._api_sync(
                    user=user, guild_settings=guild_settings
                )
                sync_errors += api_errors
                sync_status = False if status is False else sync_status

                return sync_status, sync_errors

        return sync_status, sync_errors


def setup(bot):
    """
    Disnake setup function
    :param bot: discord bot client
    """
    bot.add_cog(SyncCore(bot))
    logger.info("Loaded SyncCore")