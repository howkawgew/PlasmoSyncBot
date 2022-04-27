import logging

from plasmosync import log
from plasmosync import settings
from plasmosync.bot import PlasmoSync

log.setup()

bot = PlasmoSync.create()
logger = logging.getLogger(__name__)

# bot.load_extension("plasmosync.ext.core")
bot.load_extensions("plasmosync/ext")

bot.run(settings.TOKEN)  # 1
