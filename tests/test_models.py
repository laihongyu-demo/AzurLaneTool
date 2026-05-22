"""
模型层模块单元测试。
"""

import unittest
from datetime import date

from models.base_model import BaseModel
from models.ship_model import ShipModel


class TestBaseModel(unittest.TestCase):
    """基础模型测试类。"""

    def testToDict(self):
        """测试模型转字典。"""
        ship = ShipModel(id=1, name="Test Ship", capacity=1000)
        result = ship.toDict()
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["name"], "Test Ship")
        self.assertEqual(result["capacity"], 1000)

    def testFromDict(self):
        """测试字典转模型。"""
        data = {"id": 1, "name": "Test Ship", "capacity": 1000, "status": "active"}
        ship = ShipModel.fromDict(data)
        self.assertEqual(ship.id, 1)
        self.assertEqual(ship.name, "Test Ship")
        self.assertEqual(ship.capacity, 1000)

    def testUpdate(self):
        """测试模型更新。"""
        ship = ShipModel(id=1, name="Old Name", capacity=1000)
        ship.update(name="New Name", capacity=2000)
        self.assertEqual(ship.name, "New Name")
        self.assertEqual(ship.capacity, 2000)


class TestShipModel(unittest.TestCase):
    """船舶模型测试类。"""

    def testCreateShip(self):
        """测试创建船舶实例。"""
        ship = ShipModel(
            id=1,
            name="Test Ship",
            capacity=5000,
            launch_date=date(2024, 1, 1),
            status="active"
        )
        self.assertEqual(ship.name, "Test Ship")
        self.assertEqual(ship.capacity, 5000)
        self.assertEqual(ship.status, "active")

    def testDefaultValues(self):
        """测试默认值。"""
        ship = ShipModel()
        self.assertEqual(ship.name, "")
        self.assertEqual(ship.capacity, 0)
        self.assertEqual(ship.status, "active")


if __name__ == "__main__":
    unittest.main()
