/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { EmployeeFormController } from "@hr/views/form_view";

/**
 * Patch EmployeeFormController to fix Odoo 20/master bug where
 * `record._values.employee_id.id` throws TypeError: Cannot read properties of undefined (reading 'id')
 * when saving changes to an employee record (such as employee name).
 */
patch(EmployeeFormController.prototype, {
    async onWillSaveRecord(record, changes) {
        if (!record._values) {
            record._values = {};
        }

        // Guard employee_id
        if (!record._values.employee_id || !record._values.employee_id.id) {
            const empId = (typeof record._values.employee_id === "number")
                ? record._values.employee_id
                : (record.resId || record._config?.resId);
            record._values.employee_id = { id: empId };
        }

        // Guard version_id
        if (!record._values.version_id || !record._values.version_id.id) {
            const vId = (typeof record._values.version_id === "number")
                ? record._values.version_id
                : (Array.isArray(record._values.version_id) ? record._values.version_id[0] : null)
                || (typeof record.data?.version_id === "number" ? record.data.version_id : null)
                || (Array.isArray(record.data?.version_id) ? record.data.version_id[0] : null)
                || record.data?.version_id?.id
                || record.resId
                || record._config?.resId;
            if (vId) {
                record._values.version_id = { id: vId };
            }
        }

        return super.onWillSaveRecord(...arguments);
    },
});
