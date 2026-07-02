python3 -c "
import asyncio
from dotenv import load_dotenv
load_dotenv()
from main import get_redis

async def wipe():
    r = await get_redis()
    await r.delete('cours_full', 'cours_response', 'last_sync_date', 'last_debug_log')
    print('Wiped.')
    await r.aclose()

asyncio.run(wipe())
"