import os
import unittest
from argparse import Namespace
import shutil

import bilby_pipe


class TestSlurm(unittest.TestCase):
    def setUp(self):
        self.outdir = "test_outdir"
        self.directory = os.path.abspath(os.path.dirname(__file__))
        self.test_args = Namespace(
            ini="tests/test_dag_ini_file.ini",
            submit=False,
            outdir=self.outdir,
            label="label",
            accounting="accounting.group",
            detectors="H1",
            coherence_test=False,
            n_parallel=1,
            injection=False,
            injection_file=None,
            n_injection=None,
            singularity_image=None,
            local=False,
            queue=1,
            create_summary=False,
            sampler=["nestle"],
            gps_file=None,
            webdir=".",
            email="test@test.com",
            existing_dir=None,
            local_generation=False,
            local_plot=False,
            trigger_time=0,
            deltaT=0.2,
            waveform_approximant="IMRPhenomPV2",
            request_memory="4 GB",
            request_memory_generation="4 GB",
            request_cpus=1,
            generation_seed=None,
            transfer_files=True,
            prior_file=None,
            default_prior="BBHPriorDict",
            postprocessing_executable=None,
            postprocessing_arguments=None,
            scheduler="slurm",
            scheduler_args="account=myaccount partition=mypartition",
            scheduler_module=None,
            scheduler_env=None,
            data_dict=None,
            create_plots=False,
            likelihood_type=None,
            duration=4,
            osg=True,
        )
        self.test_unknown_args = ["--argument", "value"]
        self.inputs = bilby_pipe.main.MainInput(self.test_args, self.test_unknown_args)
        self.inputs.level_A_labels = ["test"]
        self.injection_file = os.path.join(self.outdir, "example_injection_file.h5")
        self.create_injection_args = Namespace(
            outdir=self.outdir,
            label="label",
            prior_file="tests/example_prior.prior",
            n_injection=3,
            generation_seed=None,
            default_prior="BBHPriorDict",
            trigger_time=0,
            deltaT=0.2,
            gps_file=None,
            duration=4,
            post_trigger_duration=2,
        )
        ci_inputs = bilby_pipe.create_injections.CreateInjectionInput(
            self.create_injection_args, []
        )
        ci_inputs.create_injection_file(self.injection_file)

    def tearDown(self):
        del self.test_args
        del self.inputs
        shutil.rmtree(self.outdir)

    def test_create_slurm_submit(self):
        test_args = self.test_args
        inputs = bilby_pipe.main.MainInput(test_args, self.test_unknown_args)
        inputs.level_A_labels = ["test_label"]
        inputs.n_level_A_jobs = 1
        bilby_pipe.main.Dag(inputs)
        filename = os.path.join(self.outdir, "submit/label_master_slurm.sh")
        self.assertTrue(os.path.exists(filename))


if __name__ == "__main__":
    unittest.main()