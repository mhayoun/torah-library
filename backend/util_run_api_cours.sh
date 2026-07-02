#Ce JSON est ce que le frontend React va consommer
# pour afficher les cours.
curl http://localhost:8000/api/cours | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps(data, ensure_ascii=False, indent=2))
" 2>/dev/null | head -50
