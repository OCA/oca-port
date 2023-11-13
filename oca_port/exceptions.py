# Copyright 2023 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)


class ForkValueError(ValueError):
    def __init__(self, entity):
        super().__init__(entity._ref)
        self.entity = entity


class RemoteBranchValueError(ValueError):
    def __init__(self, entity):
        super().__init__(entity._ref)
        self.entity = entity
