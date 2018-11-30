#!/usr/bin/env python
"""
bilby_pipe is a command line tools for taking user input (as command line or
an ini file) and creating DAG files for submitting bilby parameter estimation
jobs.
"""
import os
import sys
import shutil
import itertools

import configargparse
import pycondor
import deepdish

from .utils import logger
from . import utils
from . import webpages


def parse_args(input_args, parser):
    """ Parse an argument list using parser generated by create_parser()

    Parameters
    ----------
    input_args: list
        A list of arguments

    Returns
    -------
    args: argparse.Namespace
        A simple object storing the input arguments
    unknown_args: list
        A list of any arguments in `input_args` unknown by the parser

    """

    if len(input_args) == 0:
        raise ValueError("No command line arguments provided")

    args, unknown_args = parser.parse_known_args(input_args)
    return args, unknown_args


def create_parser():
    """ Creates the configargparse.ArgParser for bilby_pipe """
    parser = configargparse.ArgParser(
        usage=__doc__, ignore_unknown_config_file_keys=True,
        allow_abbrev=False)
    parser.add('ini', type=str, is_config_file=True, help='The ini file')
    parser.add('--submit', action='store_true',
               help='If given, build and submit')
    parser.add('--sampler', nargs='+', default='dynesty',
               help='Sampler to use, or list of sampler to use')
    parser.add('--detectors', nargs='+', default=['H1', 'L1'],
               help='The names of detectors to include {H1, L1}')
    parser.add('--coherence-test', action='store_true')
    parser.add('--queue', type=int, default=1)
    parser.add('--label', type=str, default='LABEL',
               help='The output label')
    parser.add('--outdir', type=str, default='bilby_outdir',
               help='The output directory')
    parser.add('--create-summary', action='store_true',
               help='If true, create a summary page')
    parser.add('--accounting', type=str, required=True,
               help='The accounting group to use')
    parser.add('--X509', type=str, default=None,
               help=('If given, the path to the users X509 certificate file.'
                     'If not given, a copy of the file at the env. variable '
                     '$X509_USER_PROXY will be made in outdir and linked in '
                     'the condor jobs submission'))
    parser.add('-v', '--verbose', action='store_true', help='verbose')

    injection_parser = parser.add_argument_group(title='Injection arguments')
    injection_parser.add(
        '--injection', action='store_true', default=False,
        help='Create data from an injection file')
    injection_parser.add(
        '--injection-file', type=str, default=None,
        help='If given, an injection file')
    injection_parser.add_arg(
        '--n-injection', type=int, help='The number of injections to generate')
    return parser


class Input(object):
    """ Superclass of input handlers """

    @property
    def known_detectors(self):
        try:
            return self._known_detectors
        except AttributeError:
            return ['H1', 'L1', 'V1']

    @known_detectors.setter
    def known_detectors(self, known_detectors):
        self._known_detectors = self._convert_detectors_input(known_detectors)

    @property
    def detectors(self):
        """ A list of the detectors to include, e.g., ['H1', 'L1'] """
        return self._detectors

    @detectors.setter
    def detectors(self, detectors):
        self._detectors = self._convert_detectors_input(detectors)
        self._check_detectors_against_known_detectors()

    def _convert_detectors_input(self, detectors):
        if isinstance(detectors, str):
            det_list = self._split_string_by_space(detectors)
        elif isinstance(detectors, list):
            if len(detectors) == 1:
                det_list = self._split_string_by_space(detectors[0])
            else:
                det_list = detectors
        else:
            raise ValueError('Input `detectors` = {} not understood'
                             .format(detectors))

        det_list.sort()
        det_list = [det.upper() for det in det_list]
        return det_list

    def _check_detectors_against_known_detectors(self):
        for element in self.detectors:
            if element not in self.known_detectors:
                raise ValueError(
                    'detectors contains "{}" not in the known '
                    'detectors list: {} '.format(
                        element, self.known_detectors))

    @staticmethod
    def _split_string_by_space(string):
        """ Converts "H1 L1" to ["H1", "L1"] """
        return string.split(' ')

    @staticmethod
    def _convert_string_to_list(string):
        """ Converts various strings to a list """
        string = string.replace(',', ' ')
        string = string.replace('[', '')
        string = string.replace(']', '')
        string = string.replace('"', '')
        string = string.replace("'", '')
        string_list = string.split()
        return string_list

    @property
    def outdir(self):
        """ The path to the directory where output will be stored """
        return self._outdir

    @outdir.setter
    def outdir(self, outdir):
        utils.check_directory_exists_and_if_not_mkdir(outdir)
        self._outdir = os.path.abspath(outdir)


class MainInput(Input):
    """ An object to hold all the inputs to bilby_pipe

    Parameters
    ----------
    parser: configargparse.ArgParser, optional
        The parser containing the command line / ini file inputs
    args_list: list, optional
        A list of the arguments to parse. Defauts to `sys.argv[1:]`

    Attributes
    ----------
    ini: str
        The path to the ini file
    submit: bool
        If true, user-input to also submit the jobs
    label: str
        A label describing the job
    outdir: str
        The path to the directory where output will be stored
    queue: int
        The number of jobs to queue
    create_summary: bool
        If true, create a summary page
    accounting: str
        The accounting group to use
    coherence_test: bool
        If true, run the coherence test
    detectors: list
        A list of the detectors to include, e.g., ['H1', 'L1']
    unknown_args: list
        A list of unknown command line arguments
    x509userproxy: str
        A path to the users X509 certificate used for authentication

    """

    def __init__(self, args, unknown_args):
        logger.debug('Creating new Input object')
        logger.info('Command line arguments: {}'.format(args))

        logger.debug('Known detector list = {}'.format(self.known_detectors))

        self.unknown_args = unknown_args
        self.ini = args.ini
        self.submit = args.submit
        self.outdir = args.outdir
        self.label = args.label
        self.queue = args.queue
        self.create_summary = args.create_summary
        self.accounting = args.accounting
        self.sampler = args.sampler
        self.detectors = args.detectors
        self.coherence_test = args.coherence_test
        self.x509userproxy = args.X509

        self.injection = args.injection
        self.injection_file = args.injection_file
        self.n_injection = args.n_injection

        # These keys are used in the webpages summary
        self.meta_keys = ['label', 'outdir', 'ini',
                          'detectors', 'coherence_test',
                          'sampler', 'accounting']

    @property
    def ini(self):
        return self._ini

    @ini.setter
    def ini(self, ini):
        if os.path.isfile(ini) is False:
            raise ValueError('ini file is not a file')
        self._ini = os.path.abspath(ini)

    @property
    def n_injection(self):
        return self._n_injection

    @n_injection.setter
    def n_injection(self, n_injection):
        if n_injection is not None:
            logger.info(
                "n_injection={}, overwriting queue input".format(n_injection))
            self.queue = n_injection

    @property
    def x509userproxy(self):
        """ A path to the users X509 certificate used for authentication """
        try:
            return self._x509userproxy
        except AttributeError:
            raise ValueError(
                "The X509 user proxy has not been correctly set, please check"
                " the logs")

    @x509userproxy.setter
    def x509userproxy(self, x509userproxy):
        if x509userproxy is None:
            cert_alias = 'X509_USER_PROXY'
            try:
                cert_path = os.environ[cert_alias]
                new_cert_path = os.path.join(
                    self.outdir, '.' + os.path.basename(cert_path))
                shutil.copyfile(cert_path, new_cert_path)
                self._x509userproxy = new_cert_path
            except FileNotFoundError:
                logger.warning(
                    "Environment variable X509_USER_PROXY does not point to a"
                    " file. Try running $ligo-proxy-init albert.einstein")
            except KeyError:
                logger.warning(
                    "Environment variable X509_USER_PROXY not set"
                    " Try running $ligo-proxy-init albert.einstein")
                self._x509userproxy = None
        elif os.path.isfile(x509userproxy):
            self._x509userproxy = x509userproxy
        else:
            raise ValueError('Input X509 not a file or not understood')


class Dag(object):
    """ A class to handle the creation and building of a DAG

    Parameters
    ----------
    inputs: bilby_pipe.Input
        An object holding the inputs built from the command-line and ini file.

    Other parameters
    ----------------
    request_memory : str or None, optional
        Memory request to be included in submit file.
        request_disk : str or None, optional
        Disk request to be included in submit file.
    request_cpus : int or None, optional
        Number of CPUs to request in submit file.
    getenv : bool or None, optional
        Whether or not to use the current environment settings when running
        the job (default is None).
    universe : str or None, optional
        Universe execution environment to be specified in submit file
        (default is None).
    initialdir : str or None, optional
        Initial directory for relative paths (defaults to the directory was
        the job was submitted from).
    notification : str or None, optional
        E-mail notification preference (default is None).
    requirements : str or None, optional
        Additional requirements to be included in ClassAd.
    extra_lines : list or None, optional
        List of additional lines to be added to submit file.
    dag : Dagman, optional
        If specified, Job will be added to dag (default is None).
    arguments : str or iterable, optional
        Arguments with which to initialize the Job list of arguments
        (default is None).
    retry : int or None, optional
        Option to specify the number of retries for all Job arguments. This
        can be superseded for arguments added via the add_arg() method.
        Note: this feature is only available to Jobs that are submitted via
        a Dagman (default is None; no retries).
    verbose : int, optional
        Level of logging verbosity option are 0-warning, 1-info,
        2-debugging (default is 0).

    Notes
    -----
        The "Other Parameters" are passed directly to
        `pycondor.Job()`. Documentation for these is taken verbatim from the
        API available at https://jrbourbeau.github.io/pycondor/api.html

    """

    def __init__(self, inputs, request_memory=None, request_disk=None,
                 request_cpus=None, getenv=True, universe='vanilla',
                 initialdir=None, notification='never', requirements=None,
                 retry=None, verbose=0):
        self.request_memory = request_memory
        self.request_disk = request_disk
        self.request_cpus = request_disk
        self.getenv = getenv
        self.universe = universe
        self.initialdir = initialdir
        self.notification = notification
        self.requirements = requirements
        self.retry = retry
        self.verbose = verbose
        self.inputs = inputs

        self.dag = pycondor.Dagman(
            name='main_' + inputs.label,
            submit=self.submit_directory)
        self.jobs = []
        self.results_pages = dict()
        if self.inputs.injection:
            self.check_injection()
        self.create_generation_job()
        self.create_analysis_jobs()
        self.create_postprocessing_jobs()
        self.build_submit()

    @staticmethod
    def _get_executable_path(exe_name):
        exe = shutil.which(exe_name)
        if exe is not None:
            return exe
        else:
            raise OSError("{} not installed on this system, unable to proceed"
                          .format(exe_name))

    @property
    def generation_executable(self):
        return self._get_executable_path('bilby_pipe_generation')

    @property
    def analysis_executable(self):
        return self._get_executable_path('bilby_pipe_analysis')

    @property
    def submit_directory(self):
        return os.path.join(self.inputs.outdir, 'submit')

    def check_injection(self):
        """ If injections are requested, create an injection file """
        default_injection_file_name = '{}/{}_injection_file.h5'.format(
            self.inputs.outdir, self.inputs.label)
        if self.inputs.injection_file is not None:
            logger.info("Using injection file {}".format(self.inputs.injection_file))
        elif os.path.isfile(default_injection_file_name):
            logger.info("Using injection file {}".format(default_injection_file_name))
        else:
            logger.info("No injection file found, generating one now")
            import bilby_pipe.create_injections
            inj_args, inj_unknown_args = parse_args(
                sys.argv[1:], bilby_pipe.create_injections.create_parser())
            inj_inputs = bilby_pipe.create_injections.CreateInjectionInput(
                inj_args, inj_unknown_args)
            inj_inputs.create_injection_file()

    def create_generation_job(self):
        """ Create a job to generate the data """
        job_label = self.inputs.label + '_generation'
        job_logs_path = os.path.join(self.inputs.outdir, 'logs')
        utils.check_directory_exists_and_if_not_mkdir(job_logs_path)
        job_logs_base = os.path.join(job_logs_path, job_label)
        submit = self.submit_directory
        extra_lines = ''
        for arg in ['error', 'log', 'output']:
            extra_lines += '\n{} = {}_$(Cluster)_$(Process).{}'.format(
                arg, job_logs_base, arg[:3])
        extra_lines += '\naccounting_group = {}'.format(self.inputs.accounting)
        extra_lines += '\nx509userproxy = {}'.format(self.inputs.x509userproxy)
        arguments = '--ini {}'.format(self.inputs.ini)

        arguments += ' --cluster $(Cluster)'
        arguments += ' --process $(Process)'
        arguments += ' ' + ' '.join(self.inputs.unknown_args)
        self.generation_job = pycondor.Job(
            name=job_label,
            executable=self.generation_executable,
            submit=submit,
            request_memory=self.request_memory, request_disk=self.request_disk,
            request_cpus=self.request_cpus, getenv=self.getenv,
            universe=self.universe, initialdir=self.initialdir,
            notification=self.notification, requirements=self.requirements,
            queue=self.inputs.queue, extra_lines=extra_lines, dag=self.dag,
            arguments=arguments, retry=self.retry, verbose=self.verbose)
        logger.debug('Adding job: {}'.format(job_label))

    def create_analysis_jobs(self):
        """ Create all the condor jobs and add them to the dag """
        for job_input in self.analysis_jobs_inputs:
            self.jobs.append(self._create_analysis_job(**job_input))

    @property
    def analysis_jobs_inputs(self):
        """ A list of dictionaries enumerating all the main jobs to generate

        This contains the logic of generating multiple parallel running jobs
        The keys of each dictionary should be the keyword arguments to
        `self._create_jobs()`

        """
        logger.debug("Generating list of jobs")
        detectors_list = []
        detectors_list.append(self.inputs.detectors)
        if self.inputs.coherence_test:
            for detector in self.inputs.detectors:
                detectors_list.append([detector])

        sampler_list = self.inputs.sampler

        prod_list = itertools.product(detectors_list, sampler_list)
        jobs_inputs = []
        for detectors, sampler in prod_list:
            jobs_inputs.append(dict(detectors=detectors, sampler=sampler))

        logger.debug("List of job inputs = {}".format(jobs_inputs))
        return jobs_inputs

    def _create_analysis_job(self, detectors, sampler):
        """ Create a condor job and add it to the dag

        Parameters
        ----------
        detectors: list, str
            A list of the detectors to include, e.g. `['H1', 'L1']`
        sampler: str
            The sampler to use for the job

        """

        if not isinstance(detectors, list):
            raise ValueError("`detectors must be a list")

        run_label = '_'.join([self.inputs.label, ''.join(detectors), sampler])
        job_name = run_label
        job_logs_path = os.path.join(self.inputs.outdir, 'logs')
        utils.check_directory_exists_and_if_not_mkdir(job_logs_path)
        job_logs_base = os.path.join(job_logs_path, job_name)
        submit = self.submit_directory
        extra_lines = ''
        for arg in ['error', 'log', 'output']:
            extra_lines += '\n{} = {}_$(Cluster)_$(Process).{}'.format(
                arg, job_logs_base, arg[:3])
        extra_lines += '\naccounting_group = {}'.format(self.inputs.accounting)
        extra_lines += '\nx509userproxy = {}'.format(self.inputs.x509userproxy)
        arguments = '--ini {}'.format(self.inputs.ini)
        for detector in detectors:
            arguments += ' --detectors {}'.format(detector)
        arguments += ' --sampler {}'.format(sampler)
        arguments += ' --cluster $(Cluster)'
        arguments += ' --process $(Process)'
        arguments += ' ' + ' '.join(self.inputs.unknown_args)
        job = pycondor.Job(
            name=job_name,
            executable=self.analysis_executable,
            submit=submit,
            request_memory=self.request_memory, request_disk=self.request_disk,
            request_cpus=self.request_cpus, getenv=self.getenv,
            universe=self.universe, initialdir=self.initialdir,
            notification=self.notification, requirements=self.requirements,
            queue=self.inputs.queue, extra_lines=extra_lines, dag=self.dag,
            arguments=arguments, retry=self.retry, verbose=self.verbose)
        job.add_parent(self.generation_job)
        logger.debug('Adding job: {}'.format(run_label))
        self.results_pages[run_label] = '{}.html'.format(run_label)
        return job

    def create_postprocessing_jobs(self):
        """ Generate postprocessing job """
        pass

    def build_submit(self):
        """ Build the dag, optionally submit them if requested in inputs """
        if self.inputs.submit:
            self.dag.build_submit()
        else:
            self.dag.build()


class DataDump():
    def __init__(self, label, outdir, trigger_time, interferometers, meta_data,
                 process):
        self.trigger_time = trigger_time
        self.label = label
        self.outdir = outdir
        self.interferometers = interferometers
        self.meta_data = meta_data
        self.process = process

    @property
    def filename(self):
        return os.path.join(
            self.outdir, '_'.join([self.label, str(self.process), 'data_dump.h5']))

    def to_hdf5(self):
        deepdish.io.save(self.filename, self)

    @classmethod
    def from_hdf5(cls, filename=None):
        """ Loads in a data dump

        Parameters
        ----------
        filename: str
            If given, try to load from this filename

        """
        res = deepdish.io.load(filename)
        if res.__class__ == list:
            res = cls(res)
        if res.__class__ != cls:
            raise TypeError('The loaded object is not a DataDump')
        return res


def main():
    """ Top-level interface for bilby_pipe """
    args, unknown_args = parse_args(sys.argv[1:], create_parser())
    inputs = MainInput(args, unknown_args)
    # Create a Directed Acyclic Graph (DAG) of the workflow
    dag = Dag(inputs)
    # If requested, create a summary page at the DAG-level
    if inputs.create_summary:
        webpages.create_summary_page(dag)
