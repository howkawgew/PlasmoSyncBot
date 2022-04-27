import os
from typing import Union

from dotenv import load_dotenv

from config import PlasmoRP, PlasmoSMP

load_dotenv()

DEBUG = True
TOKEN = os.getenv("BOT_TOKEN")
TEST_GUILDS = [828683007635488809, 966785796902363188]
DONOR: Union[PlasmoRP, PlasmoSMP] = PlasmoRP
