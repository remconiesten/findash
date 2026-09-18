# Lokale secrets voor import/anonimiseren

1. `cp anonymize.example.json anonymize.local.json`
2. `chmod 600 anonymize.local.json`
3. Vul **echte** IBANs en `last_name` in. Meerdere IBANs per label mag. Labels moeten `Rekening …` zijn, gelijk aan de waarden in MariaDB.
4. Dit bestand is gitignored. Niet in chat plakken. Agents mogen hem niet lezen.
