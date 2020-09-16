import subprocess
import logging
import pytest
from tempfile import mkdtemp
from tempfile import mktemp
from shutil import rmtree
import os.path
from ocs_ci.ocs import constants
from ocs_ci.framework.testlib import E2ETest
from tests import helpers
from ocs_ci.framework.pytest_customization.marks import scale

PVC_NAME = 'cephfs-pvc'
POD_NAME = 'cephfs-test-pod'
DEFAULT_NS = 'default'
TARGET_DIR = '/var/lib/www/html'
TARFILE = 'cephfs.tar.gz'
SIZE = '20Gi'
TFILES = 1000000
SAMPLE_TEXT = "A"

log = logging.getLogger(__name__)


def add_million_files():
    """
    Create a directory with one million files in it.
    Tar that directory to a zipped tar file.
    Rsynch that tar file to the cephfs pod
    Extract the tar files on ceph pod onto the mounted ceph filesystem.
    """
    logging.info(f"Creating {TFILES} files on Cephfs")
    ntar_loc = mkdtemp()
    tarfile = os.path.join(ntar_loc, TARFILE)
    new_dir = mkdtemp()
    for i in range(0, TFILES):
        fname = mktemp(dir=new_dir)
        with open(fname, 'w') as out_file:
            out_file.write(SAMPLE_TEXT)
        if i % 100000 == 99999:
            logging.info(f'{i} local files created')
    tmploc = ntar_loc.split('/')[-1]
    subprocess.run([
        'tar',
        'cfz',
        tarfile,
        '-C',
        new_dir,
        '.'
    ])
    subprocess.run([
        'oc',
        '-n',
        'default',
        'rsync',
        ntar_loc,
        f'{POD_NAME}:{TARGET_DIR}'
    ])
    subprocess.run([
        'oc',
        '-ntproc=n',
        'default',
        'rsh',
        POD_NAME,
        'mkdir',
        f'{TARGET_DIR}/x'
    ])
    subprocess.run([
        'oc',
        '-n',
        'default',
        'rsh',
        POD_NAME,
        'tar',
        'xf',
        f'{TARGET_DIR}/{tmploc}/{TARFILE}',
        '-C',
        f'{TARGET_DIR}/x'
    ])
    rmtree(new_dir)
    os.remove(tarfile)


class MillionFilesOnCephfs(object):
    """
    Create pvc and cephfs pod, make sure that the pod is running.
    """
    def __init__(self):
        self.cephfs_pvc = helpers.create_pvc(
            constants.DEFAULT_STORAGECLASS_CEPHFS,
            pvc_name=PVC_NAME,
            namespace=DEFAULT_NS,
            size=SIZE
        )
        self.cephfs_pod = helpers.create_pod(
            interface_type=constants.CEPHFILESYSTEM,
            pvc_name=self.cephfs_pvc.name,
            namespace=DEFAULT_NS,
            node_name='compute-0',
            pod_name=POD_NAME
        )
        helpers.wait_for_resource_state(self.cephfs_pod, "Running", timeout=300)
        logging.info("pvc and cephfs pod created")

    def cleanup(self):
        self.cephfs_pod.delete()
        self.cephfs_pvc.delete()
        logging.info("Teardown complete")


@pytest.fixture(scope='session')
def million_file_cephfs(request):
    million_file_cephfs = MillionFilesOnCephfs()

    def teardown():
        million_file_cephfs.cleanup()
    request.addfinalizer(teardown)


@scale
@pytest.mark.parametrize(
    argnames=[
        "add_files",
    ],
    argvalues=[
        pytest.param(
            *[True]
        ),
    ]
)
class TestMillionCephfsFiles(E2ETest):
    """
    Million cephfs files tester.
    """
    def test_scale_million_cephfs_files(self, million_file_cephfs, add_files):
        """
        args:
            million_file_cephfs -- fixture
            add_files (boolean) -- add 1,000,000 files to the cephfs pod if True
        """
        if add_files:
            add_million_files()
        proc = subprocess.Popen(
            f'oc -n {DEFAULT_NS} rsh {POD_NAME} df | grep {TARGET_DIR}',
            shell=True,
            stdout=subprocess.PIPE
        )
        dfoutput = proc.communicate()[0]
        logging.info(f"Df results on ceph pod -- {dfoutput}")
