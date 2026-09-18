-- Read-only user for the findash dashboard.
-- Do not put a real password in this file. Generate a copy with:
--   .venv/bin/python scripts/render_create_user_sql.py
-- then run the gitignored file docs/sql/create-findash-user.local.sql
-- as a MariaDB admin (phpMyAdmin or SSH). Never commit that copy.
--
-- Privileges: SELECT only on n8n.FinBotTransactions and
-- n8n.FinBotTransactionsCC. No other tables, no writes, no GRANT OPTION.
--
-- Hosts: localhost / loopback (later Docker or Home Assistant) and RFC1918
-- (LAN + VPN). MariaDB 11.4 accepts IP/netmask in the host part.

CREATE USER IF NOT EXISTS 'findash'@'localhost'              IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'findash'@'127.0.0.1'              IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'findash'@'::1'                    IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'findash'@'10.0.0.0/255.0.0.0'     IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'findash'@'172.16.0.0/255.240.0.0' IDENTIFIED BY 'CHANGE_ME';
CREATE USER IF NOT EXISTS 'findash'@'192.168.0.0/255.255.0.0' IDENTIFIED BY 'CHANGE_ME';

ALTER USER 'findash'@'localhost'              IDENTIFIED BY 'CHANGE_ME';
ALTER USER 'findash'@'127.0.0.1'              IDENTIFIED BY 'CHANGE_ME';
ALTER USER 'findash'@'::1'                    IDENTIFIED BY 'CHANGE_ME';
ALTER USER 'findash'@'10.0.0.0/255.0.0.0'     IDENTIFIED BY 'CHANGE_ME';
ALTER USER 'findash'@'172.16.0.0/255.240.0.0' IDENTIFIED BY 'CHANGE_ME';
ALTER USER 'findash'@'192.168.0.0/255.255.0.0' IDENTIFIED BY 'CHANGE_ME';

GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'localhost';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'localhost';
GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'127.0.0.1';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'127.0.0.1';
GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'::1';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'::1';
GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'10.0.0.0/255.0.0.0';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'10.0.0.0/255.0.0.0';
GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'172.16.0.0/255.240.0.0';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'172.16.0.0/255.240.0.0';
GRANT SELECT ON `n8n`.`FinBotTransactions`   TO 'findash'@'192.168.0.0/255.255.0.0';
GRANT SELECT ON `n8n`.`FinBotTransactionsCC` TO 'findash'@'192.168.0.0/255.255.0.0';

FLUSH PRIVILEGES;
