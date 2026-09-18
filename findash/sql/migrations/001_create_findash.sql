-- Primary schema: findash (create the database in the HA MariaDB add-on GUI
-- with utf8mb4 / utf8mb4_unicode_ci). Fallback: replace schema `findash` with
-- `n8n` and set FINDASH_DATABASE=n8n. Run as MariaDB admin, not findash.
-- GRANT SELECT ON findash.* is add-on GUI rights, not this file.

CREATE TABLE IF NOT EXISTS `findash`.`ui_string` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `string_key` VARCHAR(128) NOT NULL,
  `locale` CHAR(5) NOT NULL,
  `text` VARCHAR(512) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ui_key_locale` (`string_key`, `locale`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `findash`.`term` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `namespace` VARCHAR(32) NOT NULL,
  `source_nl` VARCHAR(191) NOT NULL,
  `locale` CHAR(5) NOT NULL,
  `text` VARCHAR(191) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_term_ns_src_loc` (`namespace`, `source_nl`, `locale`),
  KEY `idx_term_lookup` (`locale`, `namespace`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
