ALTER TABLE `findash`.`category_suggestion`
  ADD COLUMN IF NOT EXISTS `layer` VARCHAR(16) NOT NULL DEFAULT 'none' AFTER `neighbor_n`;
