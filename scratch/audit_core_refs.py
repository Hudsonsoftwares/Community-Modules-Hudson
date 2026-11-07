import sys
sys.path.insert(0, r"C:\Program Files\Odoo 20.0.20260927\server")
import odoo
from odoo import tools
import xml.etree.ElementTree as ET
import glob
import os
import re

tools.config.parse_config(['-c', r'C:\Program Files\Odoo 20.0.20260927\server\odoo.conf'])
registry = odoo.modules.registry.Registry('HudsonTest')

xml_files = glob.glob(r"c:\odoo-custom-addons\dental_addons\dental_core\**\*.xml", recursive=True)

missing_refs = []

with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    # We want to check refs that point outside dental_core
    for f in xml_files:
        try:
            tree = ET.parse(f)
            root = tree.getroot()
            for elem in root.iter():
                # check ref attribute
                for attr_name in ['ref', 'action', 'parent']:
                    val = elem.get(attr_name)
                    if val and '.' in val:
                        mod = val.split('.')[0]
                        if mod not in ['dental_core']:
                            # check if in depends of dental_core
                            # dental_core depends: base, dental_base, dental_patient, dental_catalog, dental_appointment, hr, mail, account, crm, maintenance, hr_maintenance
                            depends = ['base', 'dental_base', 'dental_patient', 'dental_catalog', 'dental_appointment', 'hr', 'mail', 'account', 'crm', 'maintenance', 'hr_maintenance', 'hr_holidays', 'calendar']
                            if mod not in depends:
                                missing_refs.append((f, elem.tag, attr_name, val, f"Module '{mod}' is NOT in dental_core depends!"))
                            else:
                                res = env.ref(val, raise_if_not_found=False)
                                if not res:
                                    missing_refs.append((f, elem.tag, attr_name, val, f"ID not found in DB!"))
        except Exception as e:
            print(f"Error parsing {f}: {e}")

print("=== AUDIT RESULTS ===")
if not missing_refs:
    print("ALL EXTERNAL REFS VALID!")
else:
    for item in missing_refs:
        print(f"File: {os.path.basename(item[0])} | Tag: {item[1]} | Attr: {item[2]}='{item[3]}' -> {item[4]}")
