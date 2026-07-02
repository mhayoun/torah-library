cd backend
# clean redis
./util_clean_redis.sh
# build from scratch
curl -X POST http://localhost:8000/api/sync