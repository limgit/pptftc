import random
import time
from pathlib import Path
from typing import List, Text, Tuple, Dict

import os
from xml.etree.ElementTree import parse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pygit2
import logging

from subprocess import call, DEVNULL

from models import *


class DataExtractor:
    TEST_REPORT_PATH = 'test.xml'
    COVERAGE_REPORT_PATH = 'cov.xml'

    SETUP_COMMAND = 'python setup.py install'
    TEST_COMMAND = 'python -m pytest -q --junit-xml=' + TEST_REPORT_PATH
    COVERAGE_COMMAND = 'python -m pytest -q {} --cov --cov-report=xml:' + COVERAGE_REPORT_PATH

    def __init__(self, db_path: Path):
        # Logger setup
        self.__logger = logging.getLogger('DataExtractor')
        self.__logger.setLevel(logging.DEBUG)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(
            logging.Formatter('[%(levelname)s] %(asctime)s: (%(name)s) %(message)s')
        )
        self.__logger.addHandler(ch)

        # Session setup
        engine_url = 'sqlite:///{}'.format(db_path.absolute())
        engine = create_engine(engine_url)

        self.__session = Session(engine)

        # Define class constants
        self.__TAG_REFNAME = "refs/tags/pptftc"

    def run(self):
        clone_root = Path('cloned_projects')
        clone_root.mkdir(exist_ok=True)

        # 1. Retrieve git project urls
        self.__logger.info("Reading projects list...")
        projects = self.__session.query(Project).all()
        self.__logger.info("Total " + str(len(projects)) + " projects are read.")
        for project in projects:
            project_dir = (clone_root / project.id.replace('/', '_')).resolve()
            # 2. Clone the repository
            try:
                self.__logger.info("Cloning " + project.id + " into '" + str(project_dir) + "'...")
                repo = pygit2.clone_repository(project.git_url, str(project_dir))
                # Create an tag for current HEAD
                repo.create_reference(self.__TAG_REFNAME, repo.head.target)
            except ValueError:
                self.__logger.info("'" + str(project_dir) + "' exists. Skip cloning.")
                repo = pygit2.Repository(str(project_dir / '.git'))
            # Checkout the tag
            repo.checkout(
                repo.lookup_reference(self.__TAG_REFNAME)
            )
            os.chdir(str(project_dir))

            # TODO: 3. Run TC and add it to Test Table
            # TODO: only being tested with ambv_black project
            # TODO: redirect stderr to logger?
            setup_result = call(DataExtractor.SETUP_COMMAND.split(), stdout=DEVNULL)
            if setup_result != 0:
                continue

            test_result = call(DataExtractor.TEST_COMMAND.split(), stdout=DEVNULL)
            if test_result != 0:
                continue

            tcs = self._collect_tcs(project_dir / DataExtractor.TEST_REPORT_PATH)

            # TODO: 4. Run coverage and add it to Coverage Table
            for tc in tcs:
                coverage_result = call(
                    DataExtractor.COVERAGE_COMMAND.format(tc).split(),
                    stdout=DEVNULL
                )

                if coverage_result != 0:
                    continue

                coverages = self._collect_coverages(project_dir / DataExtractor.COVERAGE_REPORT_PATH)
                print(coverages)

                break

            # TODO: 5. Run git blame and add it to File Table

            # TODO: 6. Repeat for previous commit

    def _collect_tcs(self, xml_root: Path) -> Dict[Text, Tuple[int, float, bool]]:
        tcs = {}

        root_node = parse(xml_root).getroot()
        tc_nodes = root_node.findall('testcase')

        for tc_node in tc_nodes:
            class_name = tc_node.get('classname').rsplit('.')[-1]
            file_name = tc_node.get('file')
            tc_name = tc_node.get('name')
            tc_id = '{}::{}::{}'.format(file_name, class_name, tc_name)

            tc_loc = int(tc_node.get('line'))
            tc_time = float(tc_node.get('time'))

            tc_failed = bool(list(tc_node.getiterator('failure')))
            tc_error = bool(list(tc_node.getiterator('error')))  # error within TC
            tc_skipped = bool(list(tc_node.getiterator('skipped')))

            # currently, skipped tc is regarded as passed TC
            tc_passed = not (tc_failed or tc_error)

            tcs[tc_id] = (tc_loc, tc_time, tc_passed)

        return tcs

    def _collect_coverages(self, xml_root: Path) -> Dict[Text, List[int]]:
        coverages = {}

        root_node = parse(xml_root).getroot()
        file_nodes = root_node.findall('packages/package/classes/class')

        for file_node in file_nodes:
            line_nodes = file_node.findall('lines/line')
            hit_line_nodes = filter(lambda x: x.get('hits') == '1', line_nodes)
            hit_lines = list(map(lambda x: int(x.get('number')), hit_line_nodes))

            coverages[file_node.get('filename')] = hit_lines

        return coverages


def prepare_session(path: Path) -> Session:
    engine_url = 'sqlite:///{}'.format(path.absolute())
    engine = create_engine(engine_url)
    session = Session(engine)

    Base.metadata.create_all(engine)

    return session


def load_projects(path: Path) -> List[Tuple[Text, Text]]:
    return [
        Project(
            id='/'.join(line.split('/')[-2:]), git_url=line
        ) for line in path.read_text().split() if line
    ]


def main():
    db_root = Path('db/')
    db_root.mkdir(exist_ok=True)
    # db_path = db_root / '{}.sqlite'.format(int(time.time()))
    db_path = db_root / 'db.sqlite'
    projects_path = Path('target_projects.txt')

    session = prepare_session(db_path)
    projects = load_projects(projects_path)
    for project in projects:
        # insert if do not exist, update if exist.
        session.merge(project)
    session.commit()

    # Extract the data
    DataExtractor(db_path).run()

    tests = session.query(Test).all()

    random_order = random.shuffle(tests)
    runtime_order = session.query(Test).order_by(Test.run_time).all()
    loc_order = session.query(Test).order_by(Test.loc).all()

#    for instance in tests:
#        print(instance.loc, instance.run_time)
#        project = session.query(Project).filter(Project.id == instance.project_id).one()


if __name__ == '__main__':
    main()
