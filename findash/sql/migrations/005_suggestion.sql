CREATE TABLE IF NOT EXISTS `findash`.`category_suggestion` (
  `src` ENUM('bank','cc') NOT NULL,
  `transactie_id` CHAR(40) NOT NULL,
  `hoofd` VARCHAR(191) NOT NULL,
  `sub` VARCHAR(191) NOT NULL,
  `score` DECIMAL(6,4) NOT NULL,
  `unanimous` TINYINT(1) NOT NULL,
  `neighbor_n` SMALLINT UNSIGNED NOT NULL,
  `disagrees` TINYINT(1) NOT NULL,
  `computed_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`src`, `transactie_id`),
  KEY `idx_sug_disagrees` (`disagrees`, `score`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
