cd backend
# clean redis
./util_clean_redis.sh

#Pour tester juste la découverte +
#le parcours des playlists (sans rien écrire dans Redis) :
cd backend
python debug_sync.py --verbose

# generate keywords
source venv/bin/activate
python3 backfill_halacha_transcripts.py --limit 1

# simulate cron (backend) from real (frontend)
curl -i https://rav-aaron-butbul.vercel.app/api/sync \
  -H "Authorization: Bearer 90d03b45b7306005c2ec37d3eb4fcc6475957c4fd95317ed9fefebac94a6b6af"

#simulate cron from localhost
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
# sync
curl -X POST http://localhost:8000/api/sync


#run frontend localhost
npm run dev

# tail crontab
tail -f /home/moshe/backfill_cron.log
cat /home/moshe/backfill_cron.log
grep CRON /var/log/syslog | tail -20
journalctl -u cron --since "10 minutes ago"


python3 util_purge_private_videos.py          # dry run first
python3 util_purge_private_videos.py --apply  # actually removes it