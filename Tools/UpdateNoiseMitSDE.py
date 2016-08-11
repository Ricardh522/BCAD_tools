import arcpy
import os
import sys
import logging
from arcpy import da
from arcpy import env
from collections import Counter
import traceback
env.overwriteOutput = 1


# location and name of output log file
def setup_logging():
    log_name = "C:\\Temp\NoiseMit_logfile.txt"
    log_file = open(log_name, 'w')
    log_file.close()
    logging.basicConfig(level=logging.DEBUG,
                        filename=log_name,
                        filemode='w')
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

# folder to store the connection files created in the script
out_f = env.scratchFolder

# name of the connection file to the default version
out_n = "Weaver.sde"

# name of the version to be created for editing
edit_connection_name = "NoiseMit.sde"

# name of the database instance
#inst = "ARORALAPTOP50\SDESQLEXPRESS"
inst = r"sql-server-azure.database.windows.net"

# username for the database user
#uid = "Richard"
uid = "bcad"

# password for the database user
#pwd = "Heddie01!"
pwd = "AroraGIS123"

# name of the database
#database = "DEVELOPMENT_BCAD.sde"
database = "bcad_noise"

# variable for the parent version of the database
p_version = "dbo.DEFAULT"

# name of building polygon feature class
# TODO - create a user parameter to point to the target building feature class
bldgs = r"Building_Information"

# sql table used to update the geodatabase table
# TODO - create a user parameter to point to the SQL Table from Weaver
SQL_Table = ""

# GDB table with holds the weaver data from the sql table
# TODO - create a user parameter to point to the GDB Table in the relationship
GDB_Table = ""

# attribute fields on the building feature class that need to be selected by the user
building_attributes = {"Project Name": "projectName",
                       "Phase Name": "phaseName",
                       "Folio Number": "folioId"}

# attribute fields on the weaver geodatabase table that need to be selected by the user
weaver_attributes = {"Project Name": "ProjectName",
                     "Phase Name": "PhaseName",
                     "Folio Number": "FolioNumber"}

# name of the dataset that holds the Noise Mitigation data
dataset = "NoiseMitigation"

opt = {"account_authentication": "DATABASE_AUTH",
               "username": uid,
               "password": pwd,
               "save_user_pass": "SAVE_USERNAME",
               "database": database,
               "schema": "#",
               "version_type": "TRANSACTIONAL",
               "version": p_version,
               "date": ""}

plat = "SQL_SERVER"


def compare_fields(sql_table, existing_table):
    """Compare the fields between the tables to catch a schema change"""
    read_fields = arcpy.ListFields(sql_table)
    read_field_names = [f.name for f in read_fields]

    existing_fields = arcpy.ListFields(existing_table)
    existing_field_names = [f.name for f in existing_fields]

    # The only missing field should be ObjectID because the sql table is not registered with the geodatabase
    new_fields = [f for f in read_field_names if f not in existing_field_names]
    missing_fields = [f for f in existing_field_names if f not in read_field_names]

    _match_fields = [f for f in existing_field_names if f in read_field_names]
    if "OBJECTID" in _match_fields:
        _match_fields.remove("OBJECTID")

    if len(new_fields):
        raise Exception("A schema change exists in the updated weaver table :: {}".format(new_fields))

    if missing_fields != [u'OBJECTID'] and missing_fields != []:
        raise Exception("The updated weaver table is missing fields :: {}\
                        A Schema change may be needed to import the table,\
                        or else the column will be empty".format(missing_fields))

    # verify that the necessary tables exist
    for x in [sql_table, existing_table]:
        if not arcpy.Exists(x):
            logging.error("the target table and the building are not found")
            raise Exception()

    # Add all of the rows from the weaver sql table to a list
    add_rows = []
    with da.SearchCursor(sql_table, _match_fields) as cursor:
        for row in cursor:
            add_rows.append(row)
    del cursor

    exist_rows = []
    with da.SearchCursor(existing_table, _match_fields) as cursor:
        for row in cursor:
            # the rows from the GDB table, are identical to any row in the list, remove that row from the list
            if row in add_rows:
                add_rows.remove(row)
                pass
            # if the row is not in the add_rows, then add it to the exist_rows to remove
            else:
                exist_rows.append(row)
    del cursor

    compare_result = 0
    if len(add_rows) or len(exist_rows):
        compare_result += 1

    return {"match_fields": _match_fields,
            "compare_result": compare_result,
            "add_rows": add_rows,
            "exist_rows": exist_rows}


def print_connection_info(workspace):
    """print the connection properties of the workspace describe object"""
    x = arcpy.Describe(workspace)
    cp = x.connectionProperties
    print cp.database, cp.version


def clean_row(_row):
    """take an input row from a cursor, clean it, then return the cleaned row"""
    cleaned_row = []
    for _x in _row:
        if _x is None:
            _x = "unknown"
        _x = _x.strip()
        cleaned_row.append(_x)
    return cleaned_row


class VersionException(Exception):
    """throw this when handling exception with managing versions"""
    def __init__(self, *args):
        exc_t, exc_v, exc_trace = sys.exc_info()
        traceback.print_exception(exc_t, exc_v, exc_trace,
                                  limit=2, file=sys.stdout)


class SdeConnector:
    def __init__(self, out_folder, out_name, platform, instance, options):
        self.out_folder = out_folder
        self.out_name = out_name
        self.platform = platform
        self.instance = instance
        self.options = options

    def create_sde_connection(self):
        # delete the sde file if it exists
        loc = os.path.join(self.out_folder, self.out_name)
        if os.path.exists(loc):
            os.remove(loc)

        sd = arcpy.CreateDatabaseConnection_management(self.out_folder, self.out_name, self.platform, self.instance,
                                                       **self.options)
        # input path to the dev sde database connection
        target_sde = sd.getOutput(0)
        if not os.path.exists(target_sde):
            raise Exception("The sde file was not created")

        env.workspace = target_sde

        if arcpy.Exists(target_sde):
            d = target_sde
        else:
            d = False
        return d


class VersionManager:
    def __init__(self, out_folder, platform, instance, target_sde, new_name, parent_version):
        self.instance = instance
        self.platform = platform
        self.out_folder = out_folder
        self.target_sde = target_sde
        self.version_name = "{}.{}".format(uid.upper(), new_name)
        self.new_name = new_name
        self.version_sde = ""
        self.parent_version = parent_version
        pass

    def clean_previous(self):
        # remove previous version if it exists
        versions = da.ListVersions(self.target_sde)
        if len(versions):
            v_names = [v.name for v in versions]
            if self.version_name in v_names:
                try:
                    arcpy.DeleteVersion_management(self.target_sde, self.version_name)
                    return True
                except:
                    raise VersionException()
            elif len(v_names) == 1:
                return True
            else:
                logging.warning("""There are versions existing in the geodatabase
                                 that may need to be removed:: {}""".format(v_names))
        else:
            logging.info("no versions found")
            return True

    def connect_version(self):
        # create version to edit
        versions = da.ListVersions(self.target_sde)
        if len(versions):
            v_names = [v.name for v in versions]
            if self.version_name in v_names:
                raise VersionException("Version already exists, must remove before proceeding")
            else:
                try:
                    arcpy.CreateVersion_management(self.target_sde, self.parent_version, self.new_name,
                                                   access_permission="PUBLIC")
                except:
                    raise VersionException()


            # create an sde connection file to the new version
            v_opt = opt.copy()
            v_opt["version"] = self.version_name

            # create SdeConnector object for the version
            version_connection = SdeConnector(self.out_folder, self.new_name, self.platform, self.instance, v_opt)
            self.version_sde = version_connection.create_sde_connection()
            return self.version_sde

        else:
            raise VersionException()

    def rec_post(self):
        try:
            # Block additional connections during rec/post
            env.workspace = self.version_sde

            arcpy.ReconcileVersions_management(self.version_sde, "BLOCKING_VERSIONS", self.parent_version,
                                               self.version_name, "LOCK_ACQUIRED",
                                               "ABORT_CONFLICTS", "BY_OBJECT", "FAVOR_TARGET_VERSION",
                                               "POST", "DELETE_VERSION", "C:\\Temp\NoiseMit_logfile.txt")

            return True
        except Exception as e:
            raise VersionException("Unable to rec/post edits :: {}".format(e.message))


class WeaverUpdater:
    """match_fields, w_table, add_rows, rem_rows, version_sde_file, editor"""
    def __init__(self, match_fields, write_table, read_rows, remove_rows, version_sde, editor):
        self.match_fields = match_fields
        self.write_table = write_table
        self.read_rows = read_rows
        self.remove_rows = remove_rows
        self.version_sde = version_sde
        self.items = {}
        self.editor = editor
        pass

    def count_pid(self):
        parcel_ids = []

        for _row in self.read_rows:
            parcel_ids.append(_row[0])

        _cnt = Counter()
        for _pid in parcel_ids:
            _cnt[_pid] += 1

        self.items = dict(_cnt)
        return self.items

    def insert_rows(self):
        try:
            self.editor.startOperation()

            insert = da.InsertCursor(self.write_table, self.match_fields)
            i = 0
            for _row in self.read_rows:
                insert.insertRow(_row)
                i += 1
            del insert

            self.editor.stopOperation()
            return i

        except Exception as h:
            print h.message

    def delete_rows(self, parcel_id):
        self.editor.startOperation()
        i = 0
        with da.UpdateCursor(self.write_table, self.match_fields, "ParcelID='{}'".format(parcel_id)) as _cursor:
            for line in _cursor:
                # delete all rows that are identical to an item in the input list
                if line in self.remove_rows:
                    _cursor.deleteRow(line)
                    i += 1
        del _cursor
        self.editor.stopOperation()
        return i

    def update_table(self, parcel_id):
        try:
            # use the update cursor to remove the rem_rows
            deleted, added = 0, 0
            if len(self.remove_rows):
                deleted = self.delete_rows(parcel_id)
            if len(self.read_rows):
                added = self.insert_rows()
            return [deleted, added]

        except Exception as f:
            print f.message

    def perform_update(self):
        # begin edit session
        # work with one pid at a time
        for pid in self.items.keys():
            self.update_table(pid)
        return True


class BuildingsUpdater:
    """buildings, w_table, building_attributes, weaver_attributes,version_sde_file, editor"""
    def __init__(self, b, rel_table, bldg_atts, weav_atts, version_sde, editor):
        self.buildings = b
        self.rel_table = rel_table
        self.bldg_folio = bldg_atts["Folio Number"]
        self.bldg_update_fields = [bldg_atts["Project Name"], bldg_atts["Phase Name"]]
        self.weav_folio = weav_atts["Folio Number"]
        self.weav_update_fields = [weav_atts["Project Name"], weav_atts["Phase Name"]]
        self.version_sde = version_sde
        self.editor = editor
        self.folios = {}

    def get_folios(self):
        with da.SearchCursor(self.buildings, self.bldg_folio) as _cursor:
            for _row in _cursor:
                cleaned_row = clean_row(_row)
                self.folios[cleaned_row[0]] = {"Phase Names": [], "Project Names": []}
        del _cursor
        return self.folios

    def update_buildings(self):
        # gather the building folio numbers as keys in a dict
        def concat_list(_input):
            """take the input multivalue list and output a string"""
            _ph = _input
            if type(_ph) == list:
                cnt = Counter()
                for w in _ph:
                    cnt[w] += 1

                _ph = ""
                if len(cnt.items()):
                    l = []
                    d = dict(cnt)

                    for k, v in d.iteritems():
                        l.append("{}:{}".format(k, v))
                    if len(l) > 1:
                        _ph = ", ".join(l)
                    else:
                        _ph = str(l[0])

            return _ph

        _folios = self.get_folios()
        fields = [self.weav_folio, self.weav_update_fields[0], self.weav_update_fields[1]]
        with da.SearchCursor(self.rel_table, fields) as _cursor:
            for _row in _cursor:
                cleaned_row = clean_row(_row)
                if cleaned_row[0] in _folios:
                    _folios[cleaned_row[0]]["Phase Names"].append(cleaned_row[1])
                    _folios[cleaned_row[0]]["Project Names"].append(cleaned_row[2])

        del _row
        del _cursor

        self.editor.startOperation()

        fields = [self.bldg_folio, self.bldg_update_fields[0], self.bldg_update_fields[1]]
        with da.UpdateCursor(self.buildings, fields) as _cursor:
            for _row in _cursor:
                cleaned_row = clean_row(_row)
                folio_id = cleaned_row[0]
                if folio_id in _folios:
                    ph = _folios[folio_id]["Phase Names"]
                    phase_name = concat_list(ph)

                    pn = _folios[folio_id]["Project Names"]
                    project_name = concat_list(pn)

                    new_row = [folio_id, phase_name, project_name]
                    _cursor.updateRow(new_row)
                else:
                    print "{} is not in the weaver table".format(folio_id)
        del _row
        del _cursor

        self.editor.stopOperation()
        return True


def run_tool():
    """this is the main body of the tool"""
    try:
        connection = SdeConnector(out_f, out_n, plat, inst, opt)
        sde_file = connection.create_sde_connection()

        # These values need to be removed when the user parameters are created
        SQL_Table = arcpy.ListTables("*weaver_formatted")[0]
        GDB_Table = arcpy.ListTables("*WEAVER")[0]
        result = compare_fields(sql_table=SQL_Table, existing_table=GDB_Table)
        compare_result = result["compare_result"]
        match_fields = result["match_fields"]
        add_rows = result["add_rows"]
        exist_rows = result["exist_rows"]

        # This needs to run one time to populate the attributes for PhaseName and ProjectName on the buildings
        if compare_result or not compare_result:
            # create VersionManager class object to create new version, connect to it,
            # and create an sde connection file, set as current workspace
            # out_folder, platform, instance, target_sde, version_name, new_name, parent_version
            version_manager = VersionManager(out_f, plat, inst, sde_file,
                                             "NoiseMit", p_version)
            version_manager.clean_previous()
            version_sde_file = version_manager.connect_version()

            editor = da.Editor(version_sde_file)
            editor.startEditing()

            # create WeaverUpdater class object
            weaver_updater = WeaverUpdater(match_fields, GDB_Table, add_rows, exist_rows, version_sde_file, editor)

            # get the number for rows per parcel ID
            pid_dict = weaver_updater.count_pid()
            # should return True when editing is complete
            table_updated = weaver_updater.perform_update()

            # get the noise mit dataset and the buildings feature class
            dataset_workspace = arcpy.ListDatasets("*{}*".format(dataset))[0]
            buildings = arcpy.ListFeatureClasses("*{}*".format(bldgs), "Polygon", dataset_workspace)[0]
            # create BuildingUpdater class object
            building_updater = BuildingsUpdater(buildings, GDB_Table, building_attributes, weaver_attributes,
                                                version_sde_file, editor)
            # should return True when editing it complete
            buildings_updated = building_updater.update_buildings()

            editor.stopEditing(True)
            del editor

            # move edits to the default version, and delete the noisemit version
            version_manager.rec_post()
        else:
            print "The files are identical, no edits needed"

        env.workspace = sde_file
        # get the noise mit dataset and the buildings feature class
        dataset_workspace = arcpy.ListDatasets("*{}*".format(dataset))[0]
        buildings = arcpy.ListFeatureClasses("*{}*".format(bldgs), "Polygon", dataset_workspace)[0]

        fields = [x for x in building_attributes.itervalues()]
        cursor = da.SearchCursor(buildings, fields)
        values = cursor.next()
        del cursor
        print values
        return True

    except:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        traceback.print_exception(exc_type, exc_value, exc_traceback,
                                  limit=2, file=sys.stdout)




