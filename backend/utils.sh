cd backend
# clean redis
./util_clean_redis.sh
# build from scratch
curl -X POST http://localhost:8000/api/sync

#Pour tester juste la découverte +
#le parcours des playlists (sans rien écrire dans Redis) :
cd backend
python debug_sync.py --verbose

# generate keywords
source venv/bin/activate
python3 backfill_halacha_transcripts.py --limit 1
