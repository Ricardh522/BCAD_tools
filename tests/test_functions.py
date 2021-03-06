import os
import unittest
from unittest import TestCase

import arcpy

import utils.UpdateNoiseMitSDE as Code
from BCAD_NoiseMit_Tools import CARsGDBUpdate as PythonTool
from utils.UpdateNoiseMitSDE import SdeConnector as Connector


class TestClean_row(TestCase):
    def test_clean_row(self):
        # [target_fields, field_names, _row]
        target_fields = {
            "first": {
                "type": "String",
                "length": 2
            },
            "second": {
                "type": "Double",
                "length": None
            },
            "third": {
                "type": "String",
                "length": 2
            },
            "fourth": {
                "type": "String",
                "length": 4
            }
        }
        field_names = ["First", "Second", "Third", "Fourth"]

        test_row = ["   ", None, "  apple", "tree  "]
        row = Code.clean_row(target_fields, field_names, test_row)
        print(row)
        self.assertListEqual(["", 0.0, "", "tree"], row)


class TestCompare_tables(TestCase):
    @classmethod
    def setUpClass(cls):
        """out_folder, out_name, platform, instance, options"""
        tool = PythonTool()
        parameters = tool.getParameterInfo()
        params = tool.processParameters(parameters=parameters)
        out_folder = params["connection_folder"]
        out_name = params["edit_connection_name"]
        plat = params["platform"]
        inst = params["instance"]
        opt = params["opt"]
        connector = Connector(out_f=out_folder, out_name=out_name, platform=plat,
                              instance=inst, options=opt)
        cls.sde_file = connector.create_sde_connection()
        cls.params = params

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.sde_file)
        except:
            pass
        cls.params = None

    def test_compare_tables(self):
        params = self.params
        SQL_Table = params["sql_table"]
        GDB_Table = params["gdb_table"]
        for x in [SQL_Table, GDB_Table]:
            if not arcpy.Exists(x):
                self.fail()
        compare = Code.compare_tables(sql_table=SQL_Table, gdb_table=GDB_Table)
        keys = list(compare.keys())
        keys.sort()
        # these items must be in alphabetical order!
        self.assertListEqual(["add_rows", "compare_result", "exist_rows", "folioIds",
                             "match_fields"], keys)

        if compare["compare_result"] == 0:
            for x in [compare["add_rows"], compare["exist_rows"]]:
                print("length should be 0 :: {}".format(len(x)))
                self.assertEquals(len(x), 0)

        elif compare["compare_result"] >= 1:
            rows = len(compare["add_rows"]) + len(compare["exist_rows"])
            print("length should be greater than 0 :: {}".format(rows))
            self.assertGreaterEqual(rows, 1)
            # check that foliosIds are snagged
            self.assertGreaterEqual(len(compare["folioIds"]), 1)


class TestPrintConnection_info(TestCase):
    @classmethod
    def setUpClass(cls):
        tool = PythonTool()
        parameters = tool.getParameterInfo()
        params = tool.processParameters(parameters=parameters)
        out_folder = params["connection_folder"]
        out_name = params["edit_connection_name"]
        plat = params["platform"]
        inst = params["instance"]
        opt = params["opt"]
        connector = Connector(out_f=out_folder, out_name=out_name, platform=plat,
                              instance=inst, options=opt)
        cls.sde_file = connector.create_sde_connection()
        cls.params = params

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.sde_file)
        except:
            pass
        cls.params = None

    def test_print_connection_info(self):
        params = self.params
        ws = self.sde_file
        info = Code.print_connection_info(ws)
        self.assertTrue(info["database"])
        self.assertTrue(info["version"])


def suite():
    x = unittest.TestLoader().loadTestsFromTestCase(TestClean_row)
    y = unittest.TestLoader().loadTestsFromTestCase(TestCompare_tables)
    z = unittest.TestLoader().loadTestsFromTestCase(TestPrintConnection_info)
    return unittest.TestSuite([x, y, z])


if __name__ == '__main__':
    unittest.main()
