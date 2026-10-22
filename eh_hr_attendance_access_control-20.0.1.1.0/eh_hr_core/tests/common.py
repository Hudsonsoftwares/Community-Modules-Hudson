# -*- coding: utf-8 -*-
"""Test helpers shared by the platform and by the feature modules built on it.

The platform ships its contracts as abstract mixins, so an engine module owns
no table of its own to exercise them through. Registering a throwaway concrete
model for the duration of one test class is what lets an engine be driven
through the real ORM entry points, create, write, transitions and the audit
rows they emit, instead of through method calls on an abstract recordset.

Declare the model with ``_register = False`` so the module loader never sees
it, list it in ``test_model_defs`` and the case does the rest::

    class Doc(models.Model):
        _register = False
        _module = 'eh_hr_engine_workflow'
        _name = 'eh.hr.test.doc'
        _description = 'Workflow engine probe'
        _inherit = ['eh.hr.workflow.mixin']
        _log_access = False
        _workflow_code = 'eh.hr.test.doc'
        name = fields.Char()

    class TestX(PlatformModelCase):
        test_model_defs = (Doc,)

The table is created inside the test transaction and disappears with it; the
registry entry is removed in the class cleanup, so nothing survives the class.
``_log_access`` must be False because the metaclass only adds the create and
write audit columns to models it registers itself.
"""
from odoo.orm.model_classes import add_to_registry
from odoo.tests.common import TransactionCase


class PlatformModelCase(TransactionCase):
    """TransactionCase that registers throwaway concrete models for the
    platform's abstract mixins."""

    #: model definition classes to register for the lifetime of the class
    test_model_defs = ()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.test_model_defs:
            cls._register_platform_models(cls.test_model_defs)

    @classmethod
    def _register_platform_models(cls, model_defs):
        registry = cls.env.registry
        names = [model_def._name for model_def in model_defs]
        # Registered before the models exist so the registry is restored even
        # if the table creation below fails half way through.
        cls.addClassCleanup(cls._unregister_platform_models, registry,
                            cls.env.cr, names)
        cls.env.transaction.will_change_registry()
        for model_def in model_defs:
            add_to_registry(registry, model_def)
        registry._setup_models__(cls.env.cr, names)
        registry.init_models(cls.env.cr, names, {'module': model_defs[0]._module})
        cls.env.invalidate_all()

    @staticmethod
    def _unregister_platform_models(registry, cr, names):
        for name in names:
            if name in registry:
                del registry[name]
        registry._setup_models__(cr)
