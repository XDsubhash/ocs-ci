"""
Test to verify PVC deletion performance
"""
import logging
import pytest
import ocs_ci.ocs.exceptions as ex
import ocs_ci.ocs.resources.pvc as pvc
from ocs_ci.framework.testlib import (
    performance, E2ETest
)

from concurrent.futures import ThreadPoolExecutor
from tests import helpers
from ocs_ci.ocs import defaults, constants
from ocs_ci.utility.performance_dashboard import push_to_pvc_time_dashboard

log = logging.getLogger(__name__)


@performance
class TestPVCDeletionPerformance(E2ETest):
    """
    Test to verify PVC deletion performance
    """

    @pytest.fixture()
    def base_setup(
        self, request, interface_iterate, storageclass_factory
    ):
        """
        A setup phase for the test

        Args:
            interface_iterate: A fixture to iterate over ceph interfaces
            storageclass_factory: A fixture to create everything needed for a
                storageclass
        """
        self.interface = interface_iterate
        self.sc_obj = storageclass_factory(self.interface)

    @pytest.mark.parametrize(
        argnames=["pvc_size"],
        argvalues=[
            pytest.param(
                *['1Gi'], marks=pytest.mark.polarion_id("OCS-2005")
            ),
            pytest.param(
                *['10Gi'], marks=pytest.mark.polarion_id("OCS-2006")
            ),
            pytest.param(
                *['100Gi'], marks=pytest.mark.polarion_id("OCS-2007")
            ),
            pytest.param(
                *['1Ti'], marks=pytest.mark.polarion_id("OCS-2003")
            ),
            pytest.param(
                *['2Ti'], marks=pytest.mark.polarion_id("OCS-2004")
            ),
        ]
    )
    @pytest.mark.usefixtures(base_setup.__name__)
    def test_pvc_deletion_measurement_performance(self, teardown_factory, pvc_size):
        """
        Measuring PVC deletion time is within supported limits
        """
        logging.info('Start creating new PVC')

        pvc_obj = helpers.create_pvc(
            sc_name=self.sc_obj.name, size=pvc_size
        )
        helpers.wait_for_resource_state(pvc_obj, constants.STATUS_BOUND)
        pvc_obj.reload()
        pv_name = pvc_obj.backed_pv
        pvc_reclaim_policy = pvc_obj.reclaim_policy
        teardown_factory(pvc_obj)
        pvc_obj.delete()
        logging.info('Start deletion of PVC')
        pvc_obj.ocp.wait_for_delete(pvc_obj.name)
        if pvc_reclaim_policy == constants.RECLAIM_POLICY_DELETE:
            helpers.validate_pv_delete(pvc_obj.backed_pv)
        delete_time = helpers.measure_pvc_deletion_time(
            self.interface, pv_name
        )
        # Deletion time for CephFS PVC is a little over 3 seconds
        deletion_time = 4 if self.interface == constants.CEPHFILESYSTEM else 3
        logging.info(f"PVC deleted in {delete_time} seconds")
        if delete_time > deletion_time:
            raise ex.PerformanceException(
                f"PVC deletion time is {delete_time} and greater than {deletion_time} second"
            )
        push_to_pvc_time_dashboard(self.interface, "deletion", delete_time)

    @pytest.mark.usefixtures(base_setup.__name__)
    def test_multiple_pvc_deletion_measurement_performance(self, teardown_factory,pvc_size):
        """
        Measuring PVC deletion time of 120 PVCs in 180 seconds

        Args:
            teardown_factory: A fixture used when we want a new resource that was created during the tests
                               to be removed in the teardown phase.
        Returns:

        """
        number_of_pvcs = 120
        log.info('Start creating new 120 PVCs')

        pvc_objs = helpers.create_multiple_pvcs(
            sc_name=self.sc_obj.name,
            namespace=defaults.ROOK_CLUSTER_NAMESPACE,
            number_of_pvc=number_of_pvcs,
            size=pvc_size,
        )

        for pvc_obj in pvc_objs:
            pvc_obj.reload()
            teardown_factory(pvc_obj)
        with ThreadPoolExecutor(max_workers=5) as executor:
            for pvc_obj in pvc_objs:
                executor.submit(
                    helpers.wait_for_resource_state, pvc_obj,
                    constants.STATUS_BOUND
                )

                executor.submit(pvc_obj.reload)

        assert pvc.delete_pvcs(pvc_objs[:number_of_pvcs], True), (
            "Deletion of PVCs failed"
        )
        start_time = helpers.get_start_deletion_time(
            self.interface, pvc_objs[0].name
        )
        end_time = helpers.get_end_deletion_time(
            self.interface, pvc_objs[number_of_pvcs - 1].name,
        )
        total = end_time - start_time
        total_time = total.total_seconds()
        if total_time > 180:
            raise ex.PerformanceException(
                f"{number_of_pvcs} PVCs deletion time is {total_time} and "
                f"greater than 180 seconds"
            )
        logging.info(
            f"{number_of_pvcs} PVCs deletion time took {total_time} seconds"
        )
