"""
舰娘图鉴数据访问层模块。

封装舰娘图鉴相关的数据库 CRUD 操作。
"""

import sqlite3
from typing import Dict, List, Optional

from models.codex_model import CodexGroupModel, CodexTpModel, CodexBuffModel
from repositories.base_repository import BaseRepository
from utils.exceptions import DatabaseError


class CodexGroupRepository(BaseRepository[CodexGroupModel]):
    """
    舰娘图鉴组数据访问类。

    提供舰娘图鉴组的增删改查操作。
    """

    TABLE_NAME = "codex_group"

    def findAll(self) -> List[CodexGroupModel]:
        """查询所有舰娘图鉴记录。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            ORDER BY codex_id
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询舰娘图鉴列表失败: {e}")

    def findById(self, record_id: str) -> Optional[CodexGroupModel]:
        """根据ID查询单条舰娘图鉴记录。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_id = ?
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                row = cursor.fetchone()
                if row:
                    return CodexGroupModel.fromDict(dict(row))
                return None
        except sqlite3.Error as e:
            raise DatabaseError(f"查询舰娘图鉴详情失败: {e}")

    def findUnlocked(self) -> List[CodexGroupModel]:
        """查询已解锁的舰娘列表。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_unlock = 'Y'
            ORDER BY codex_id
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询已解锁舰娘列表失败: {e}")

    def findLocked(self) -> List[CodexGroupModel]:
        """查询未解锁的舰娘列表（按ship_aid降序、codex_id降序排列）。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_unlock = 'N'
            ORDER BY ship_aid DESC, codex_id DESC
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询未解锁舰娘列表失败: {e}")

    def insert(self, record: CodexGroupModel) -> int:
        """插入新舰娘图鉴记录。"""
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (codex_id, ship_name, ship_level, ship_star,
                   ship_rarity, ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.codex_id, record.ship_name, record.ship_level, record.ship_star,
            record.ship_rarity, record.ship_typ, record.ship_group, record.ship_aid,
            record.ship_camp, record.ship_liking, record.oath_status,
            record.codex_unlock, record.date_edit
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入舰娘图鉴记录失败: {e}")

    def update(self, record: CodexGroupModel) -> bool:
        """更新舰娘图鉴记录。"""
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET ship_name = ?, ship_level = ?, ship_star = ?, ship_rarity = ?,
                ship_typ = ?, ship_group = ?, ship_aid = ?, ship_camp = ?,
                ship_liking = ?, oath_status = ?, codex_unlock = ?, date_edit = ?
            WHERE codex_id = ?
        """
        params = (
            record.ship_name, record.ship_level, record.ship_star, record.ship_rarity,
            record.ship_typ, record.ship_group, record.ship_aid, record.ship_camp,
            record.ship_liking, record.oath_status, record.codex_unlock,
            record.date_edit, record.codex_id
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新舰娘图鉴记录失败: {e}")

    def delete(self, record_id: str) -> bool:
        """删除舰娘图鉴记录。"""
        sql = f"DELETE FROM {self.TABLE_NAME} WHERE codex_id = ?"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除舰娘图鉴记录失败: {e}")

    def updateUnlockStatus(self, codex_id: str, unlock_status: str = "Y") -> bool:
        """
        更新舰娘解锁状态。

        Args:
            codex_id: 图鉴ID。
            unlock_status: 解锁状态，默认为 'Y'。

        Returns:
            更新是否成功。
        """
        sql = f"UPDATE {self.TABLE_NAME} SET codex_unlock = ? WHERE codex_id = ?"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (unlock_status, codex_id))
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新舰娘解锁状态失败: {e}")

    def findUnlockedExcludingCollab(self) -> List[CodexGroupModel]:
        """查询已解锁的舰娘列表（排除联动舰娘）。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_unlock = 'Y' AND ship_group != '联动'
            ORDER BY codex_id
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询已解锁舰娘列表失败: {e}")

    def findLockedExcludingCollab(self) -> List[CodexGroupModel]:
        """查询未解锁的舰娘列表（排除联动舰娘）。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_unlock = 'N' AND ship_group != '联动'
            ORDER BY codex_id
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询未解锁舰娘列表失败: {e}")

    def findAllExcludingCollab(self) -> List[CodexGroupModel]:
        """查询所有舰娘列表（排除联动舰娘）。"""
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE ship_group != '联动'
            ORDER BY codex_id
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询舰娘列表失败: {e}")

    def getBulinRequirements(self) -> List[Dict]:
        """
        获取布里需求数量统计。

        Returns:
            布里需求列表，每项包含material_type和total_neededMaterial。
        """
        sql = """
            WITH StarDetails AS (
                SELECT 
                    ship_name,
                    ship_rarity,
                    ship_star,
                    CASE 
                        WHEN ship_rarity = 'N' THEN 4
                        WHEN ship_rarity = 'R' THEN 5
                        WHEN ship_rarity = 'SR' THEN 5
                        WHEN ship_rarity = 'SSR' THEN 6
                        WHEN ship_rarity = 'UR' THEN 6
                        ELSE 0
                    END AS max_star,
                    CASE 
                        WHEN ship_rarity = 'N' THEN 1
                        WHEN ship_rarity = 'R' THEN 2
                        WHEN ship_rarity = 'SR' THEN 2
                        WHEN ship_rarity = 'SSR' THEN 3
                        WHEN ship_rarity = 'UR' THEN 3
                        ELSE 0
                    END AS initial_star
                FROM codex_group
                WHERE ship_group NOT IN ('改造', '方案', 'META', '联动', '小船', 'μ兵装') AND codex_unlock = 'Y'
            ),
            MaterialsRequired AS (
                SELECT 
                    CASE 
                        WHEN ship_rarity IN ('N', 'R', 'SR') THEN 'Universal Bulin'
                        WHEN ship_rarity = 'SSR' THEN 'Trial Bulin MKII'
                        WHEN ship_rarity = 'UR' THEN 'Specialized Bulin MKIII'
                        ELSE NULL
                    END AS material_type,
                    CASE
                        WHEN ship_star < max_star - 1 THEN 
                            (max_star - 1 - ship_star) + 2
                        WHEN ship_star = max_star - 1 THEN 
                            2
                        ELSE 0
                    END AS materials_needed
                FROM StarDetails
                WHERE material_type IS NOT NULL
            )
            SELECT 
                material_type,
                SUM(materials_needed) AS total_neededMaterial
            FROM MaterialsRequired
            GROUP BY material_type
            ORDER BY material_type DESC
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询布里需求失败: {e}")

    def getRemainingLevelingCount(self) -> int:
        """
        获取剩余练级数量。

        查询条件：
        - ship_level NOT IN ('认知觉醒五阶', '认知觉醒Ⅱ')
        - ship_group IN ('常规', 'META', '方案')
        - ship_camp != 'UNIV'

        Returns:
            符合条件的舰娘数量。
        """
        sql = """
            SELECT COUNT(*) as count
            FROM codex_group
            WHERE ship_level NOT IN ('认知觉醒五阶', '认知觉醒Ⅱ')
              AND ship_group IN ('常规', 'META', '方案')
              AND ship_camp != 'UNIV'
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                row = cursor.fetchone()
                return row['count'] if row else 0
        except sqlite3.Error as e:
            raise DatabaseError(f"查询剩余练级数量失败: {e}")

    def findAwakenable(self) -> List[CodexGroupModel]:
        """
        查询可进行认知觉醒的舰娘列表。

        条件：ship_level != '认知觉醒Ⅱ' 且 codex_unlock = 'Y'
        排序：按ship_aid降序、codex_id降序排列。

        Returns:
            可觉醒舰娘模型列表。
        """
        sql = f"""
            SELECT codex_id, ship_name, ship_level, ship_star, ship_rarity,
                   ship_typ, ship_group, ship_aid, ship_camp, ship_liking,
                   oath_status, codex_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE codex_unlock = 'Y' AND ship_level != '认知觉醒Ⅱ' AND ship_group != '改造'
            ORDER BY ship_aid DESC, codex_id DESC
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexGroupModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询可觉醒舰娘列表失败: {e}")

    def updateShipLevel(self, codex_id: str, ship_level: str) -> bool:
        """
        更新舰娘觉醒等级。

        Args:
            codex_id: 图鉴ID。
            ship_level: 新的觉醒等级。

        Returns:
            更新是否成功。
        """
        sql = f"UPDATE {self.TABLE_NAME} SET ship_level = ? WHERE codex_id = ?"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (ship_level, codex_id))
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新舰娘觉醒等级失败: {e}")


class CodexTpRepository(BaseRepository[CodexTpModel]):
    """
    舰娘图鉴TP数据访问类。
    """

    TABLE_NAME = "codex_tp"

    def findAll(self) -> List[CodexTpModel]:
        """查询所有TP记录。"""
        sql = f"""
            SELECT id, codex_id, ship_name, ship_camp, ship_typ,
                   tp_value, unlock_cond, tp_unlock, date_edit
            FROM {self.TABLE_NAME}
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexTpModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询TP列表失败: {e}")

    def findById(self, record_id: int) -> Optional[CodexTpModel]:
        """根据ID查询TP记录。"""
        sql = f"""
            SELECT id, codex_id, ship_name, ship_camp, ship_typ,
                   tp_value, unlock_cond, tp_unlock, date_edit
            FROM {self.TABLE_NAME}
            WHERE id = ?
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                row = cursor.fetchone()
                if row:
                    return CodexTpModel.fromDict(dict(row))
                return None
        except sqlite3.Error as e:
            raise DatabaseError(f"查询TP详情失败: {e}")

    def insert(self, record: CodexTpModel) -> int:
        """插入TP记录。"""
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (codex_id, ship_name, ship_camp, ship_typ,
                   tp_value, unlock_cond, tp_unlock, date_edit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.codex_id, record.ship_name, record.ship_camp, record.ship_typ,
            record.tp_value, record.unlock_cond, record.tp_unlock, record.date_edit
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入TP记录失败: {e}")

    def update(self, record: CodexTpModel) -> bool:
        """更新TP记录。"""
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET codex_id = ?, ship_name = ?, ship_camp = ?, ship_typ = ?,
                tp_value = ?, unlock_cond = ?, tp_unlock = ?, date_edit = ?
            WHERE id = ?
        """
        params = (
            record.codex_id, record.ship_name, record.ship_camp, record.ship_typ,
            record.tp_value, record.unlock_cond, record.tp_unlock, record.date_edit,
            record.id
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新TP记录失败: {e}")

    def delete(self, record_id: int) -> bool:
        """删除TP记录。"""
        sql = f"DELETE FROM {self.TABLE_NAME} WHERE id = ?"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除TP记录失败: {e}")

    def updateUnlockByCodexId(self, codex_id: str, unlock_status: str = "Y") -> int:
        """
        更新指定舰娘的解锁相关TP记录。

        Args:
            codex_id: 图鉴ID（支持字母+数字组合格式）。
            unlock_status: 解锁状态。

        Returns:
            更新的记录数。
        """
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET tp_unlock = ?
            WHERE codex_id = ? AND unlock_cond = '解锁'
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (unlock_status, codex_id))
                return cursor.rowcount
        except sqlite3.Error as e:
            raise DatabaseError(f"更新TP解锁状态失败: {e}")

    def getUnlockTpDetails(self, codex_id: str) -> List[Dict]:
        """
        获取指定舰娘解锁的TP详情。

        Args:
            codex_id: 图鉴ID。

        Returns:
            解锁的TP记录列表，包含tp_value。
        """
        sql = f"""
            SELECT tp_value
            FROM {self.TABLE_NAME}
            WHERE codex_id = ? AND unlock_cond = '解锁' AND tp_unlock = 'Y'
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (codex_id,))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询TP解锁详情失败: {e}")

    def getTotalTpValue(self) -> int:
        """
        获取全部科技点总值。

        Returns:
            所有记录的tp_value总和。
        """
        sql = f"SELECT COALESCE(SUM(tp_value), 0) as total FROM {self.TABLE_NAME}"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                row = cursor.fetchone()
                return row['total'] if row else 0
        except sqlite3.Error as e:
            raise DatabaseError(f"查询科技点总值失败: {e}")

    def getUnlockedTpValue(self) -> int:
        """
        获取已解锁科技点总值。

        Returns:
            tp_unlock='Y'的记录的tp_value总和。
        """
        sql = f"SELECT COALESCE(SUM(tp_value), 0) as total FROM {self.TABLE_NAME} WHERE tp_unlock = 'Y'"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                row = cursor.fetchone()
                return row['total'] if row else 0
        except sqlite3.Error as e:
            raise DatabaseError(f"查询已解锁科技点总值失败: {e}")

    def getTpStatistics(self) -> dict:
        """
        获取科技点统计信息。

        Returns:
            包含total_tp和unlocked_tp的字典。
        """
        return {
            "total_tp": self.getTotalTpValue(),
            "unlocked_tp": self.getUnlockedTpValue()
        }


class CodexBuffRepository(BaseRepository[CodexBuffModel]):
    """
    舰娘图鉴Buff数据访问类。
    """

    TABLE_NAME = "codex_buff"

    def findAll(self) -> List[CodexBuffModel]:
        """查询所有Buff记录。"""
        sql = f"""
            SELECT id, codex_id, ship_name, ship_camp, ship_typ,
                   boost_typ, buff_typ, buff_value, buff_cond, buff_unlock
            FROM {self.TABLE_NAME}
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql)
                return [CodexBuffModel.fromDict(dict(row)) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询Buff列表失败: {e}")

    def findById(self, record_id: int) -> Optional[CodexBuffModel]:
        """根据ID查询Buff记录。"""
        sql = f"""
            SELECT id, codex_id, ship_name, ship_camp, ship_typ,
                   boost_typ, buff_typ, buff_value, buff_cond, buff_unlock
            FROM {self.TABLE_NAME}
            WHERE id = ?
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                row = cursor.fetchone()
                if row:
                    return CodexBuffModel.fromDict(dict(row))
                return None
        except sqlite3.Error as e:
            raise DatabaseError(f"查询Buff详情失败: {e}")

    def insert(self, record: CodexBuffModel) -> int:
        """插入Buff记录。"""
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (codex_id, ship_name, ship_camp, ship_typ,
                   boost_typ, buff_typ, buff_value, buff_cond, buff_unlock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            record.codex_id, record.ship_name, record.ship_camp, record.ship_typ,
            record.boost_typ, record.buff_typ, record.buff_value, record.buff_cond,
            record.buff_unlock
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"插入Buff记录失败: {e}")

    def update(self, record: CodexBuffModel) -> bool:
        """更新Buff记录。"""
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET codex_id = ?, ship_name = ?, ship_camp = ?, ship_typ = ?,
                boost_typ = ?, buff_typ = ?, buff_value = ?, buff_cond = ?, buff_unlock = ?
            WHERE id = ?
        """
        params = (
            record.codex_id, record.ship_name, record.ship_camp, record.ship_typ,
            record.boost_typ, record.buff_typ, record.buff_value, record.buff_cond,
            record.buff_unlock, record.id
        )
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, params)
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"更新Buff记录失败: {e}")

    def delete(self, record_id: int) -> bool:
        """删除Buff记录。"""
        sql = f"DELETE FROM {self.TABLE_NAME} WHERE id = ?"
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (record_id,))
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            raise DatabaseError(f"删除Buff记录失败: {e}")

    def updateUnlockByCodexId(self, codex_id: str, unlock_status: str = "Y") -> int:
        """
        更新指定舰娘的解锁相关Buff记录。

        Args:
            codex_id: 图鉴ID（支持字母+数字组合格式）。
            unlock_status: 解锁状态。

        Returns:
            更新的记录数。
        """
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET buff_unlock = ?
            WHERE codex_id = ? AND buff_cond = '解锁'
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (unlock_status, codex_id))
                return cursor.rowcount
        except sqlite3.Error as e:
            raise DatabaseError(f"更新Buff解锁状态失败: {e}")

    def getUnlockBuffDetails(self, codex_id: str) -> List[Dict]:
        """
        获取指定舰娘解锁的Buff详情。

        Args:
            codex_id: 图鉴ID。

        Returns:
            解锁的Buff记录列表，包含ship_typ, buff_typ, buff_value。
        """
        sql = f"""
            SELECT ship_typ, buff_typ, buff_value
            FROM {self.TABLE_NAME}
            WHERE codex_id = ? AND buff_cond = '解锁' AND buff_unlock = 'Y'
        """
        try:
            with self._getConnection() as conn:
                cursor = conn.execute(sql, (codex_id,))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"查询Buff解锁详情失败: {e}")
