# 1. Vide complètement Redis (efface cours_full ET cours_response)
curl -X POST https://torah-library-backend.vercel.app/api/sync

# 2. Puis depuis ton backend LOCAL (pas Vercel), lance le rebuild complet
cd ~/mydev/ravbutbul/torah-library/backend
python3 -c "
import asyncio, json, os
from dotenv import load_dotenv
load_dotenv()
from main import _build_response, get_redis

async def run():
    r = await get_redis()
    result = await _build_response(r)
    print('Total videos:', result['total'])
    for cat, vids in result['catalog'].items():
        print(f'  {cat}: {len(vids)}')
    await r.aclose()

asyncio.run(run())
"
