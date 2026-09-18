-- Extra grants when user findash already exists (e.g. phpMyAdmin created
-- 'findash'@'%') but has only USAGE. No password in this file.
-- Run as MariaDB admin, then: .venv/bin/python scripts/test_db_access.py

GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'%';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'%';
FLUSH PRIVILEGES;
