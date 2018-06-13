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

    SETUP_COMMAND = 'python setup.py develop'
    TEST_COMMAND = 'python -m pytest -q --junit-xml=' + TEST_REPORT_PATH
    COVERAGE_COMMAND = 'python -m pytest -q {} --cov --cov-report=xml:' + COVERAGE_REPORT_PATH

    TAG_REFNAME = "refs/tags/pptftc"
    WORKING_TAG_REFNAME = "refs/tags/pptftc_working"
    COMMIT_COUNT_LIMIT = 10

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

    def run(self):
        cwd = Path('.').resolve()
        clone_root = cwd / 'cloned_projects'
        clone_root.mkdir(exist_ok=True)

        # Retrieve git project urls
        self.__logger.info("Reading projects list...")
        projects = self.__session.query(Project).all()
        self.__logger.info("Total " + str(len(projects)) + " projects are read.")
        for project in projects:
            os.chdir(str(cwd))
            project_dir = clone_root / project.id.replace('/', '_')
            # Clone the repository
            try:
                self.__logger.info("Cloning " + project.id + " into '" + str(project_dir) + "'...")
                repo = pygit2.clone_repository(project.git_url, str(project_dir))
                # Create an tag for current HEAD
                repo.create_reference(DataExtractor.TAG_REFNAME, repo.head.target)
            except ValueError:
                self.__logger.info("'" + str(project_dir) + "' exists. Skip cloning.")
                repo = pygit2.Repository(str(project_dir / '.git'))
            # Checkout the tag
            repo.checkout(
                repo.lookup_reference(DataExtractor.TAG_REFNAME).resolve()
            )
            os.chdir(str(project_dir))

            commit_count = 0
            # Repeat until the specified limit is reached
            while commit_count < DataExtractor.COMMIT_COUNT_LIMIT:
                # Only target the commits that has one parent
                head_commit = repo.head.peel()
                parent_commits = head_commit.parents
                if len(parent_commits) == 0:
                    # If no parent, it is initial commit. Abort
                    self.__logger.info(
                        project.id + ":" + str(head_commit.id) + " is initial commit. End process"
                    )
                    break
                elif len(parent_commits) != 1:
                    # If multiple parent, checkout the first parent until it has one parent
                    self.__logger.info(
                        project.id + ":" + str(head_commit.id) + " has multiple parents. Move on to first parent"
                    )
                    self._checkout_commit(repo, parent_commits[0])
                    continue

                commit_count += 1
                self.__logger.info(str(commit_count) + " - Do work for " + project.id + ":" + str(head_commit.id))
                parent_commit = parent_commits[0]
                # Add commit to the Commit table
                commit_row = Commit(
                    project_id=project.id,
                    hash=str(head_commit.id),
                    parent=str(parent_commit.id),
                    timestamp=head_commit.commit_time,
                    count=commit_count
                )
                self.__session.merge(commit_row)
                self.__session.commit()

                # Add diff to the Diff table
                diff = repo.diff(parent_commit, head_commit, context_lines=0)
                hunk_tuples = []
                for patch in diff:
                    diff_delta = patch.delta
                    if diff_delta.new_file.path != diff_delta.old_file.path\
                            or not diff_delta.new_file.path.endswith('.py'):
                        continue
                    for hunk in patch.hunks:
                        hunk_tuples.append(
                            (hunk.old_start, hunk.old_lines, hunk.new_start, hunk.new_lines)
                        )
                    diff_row = Diff(
                        project_id=project.id,
                        commit_hash=str(head_commit.id),
                        path=diff_delta.new_file.path,
                        hunks=hunk_tuples
                    )
                    self.__session.merge(diff_row)
                self.__session.commit()

                # TODO: only being tested with ambv_black project
                # TODO: redirect stderr to logger?
                # Run TCs
                self.__logger.info("Running test cases for " + project.id + ":" + str(head_commit.id))
                setup_result = call(DataExtractor.SETUP_COMMAND.split(), stdout=DEVNULL)
                if setup_result != 0:
                    continue

                test_result = call(DataExtractor.TEST_COMMAND.split(), stdout=DEVNULL)
                if test_result != 0:
                    continue

                tcs = self._collect_tcs(project_dir / DataExtractor.TEST_REPORT_PATH)

                # Add TC to the Test table
                for tc in tcs:
                    test_row = Test(
                        project_id=project.id,
                        commit_hash=str(head_commit.id),
                        id=tc,
                        is_passed=tcs[tc][2],
                        run_time=tcs[tc][1],
                        loc=tcs[tc][0]
                    )
                    self.__session.merge(test_row)
                self.__session.commit()

                # Run coverage to add it to the Coverage Table
                self.__logger.info("Running coverage for each test cases in " + project.id + ":" + str(head_commit.id))
                every_files = set()
                total_tcs = len(tcs)
                tc_count = 0
                for tc in tcs:
                    # Run coverage
                    coverage_result = call(
                        DataExtractor.COVERAGE_COMMAND.format(tc).split(),
                        stdout=DEVNULL
                    )

                    if coverage_result != 0:
                        continue

                    coverages = self._collect_coverages(project_dir / DataExtractor.COVERAGE_REPORT_PATH)

                    every_files.update(coverages)

                    for file in coverages:
                        # Add coverage to the Coverage table
                        coverage_row = Coverage(
                            project_id=project.id,
                            commit_hash=str(head_commit.id),
                            tc_id=tc,
                            file_path=file,
                            lines_covered=coverages[file]
                        )
                        self.__session.merge(coverage_row)
                    # Log progress whenever tenth digit changes
                    tc_count += 1
                    if int(tc_count * 100 / total_tcs) // 10 - int((tc_count-1) * 100 / total_tcs) // 10 != 0:
                        self.__logger.info(
                            "Progress: {}% ({}/{})...".format(int(tc_count * 100 / total_tcs), tc_count, total_tcs)
                        )
                self.__session.commit()

                # Run git blame and add it to the File table
                self.__logger.info(
                    "Blame for " + str(len(every_files)) + " files in " + project.id + ":" + str(head_commit.id)
                )
                for file in every_files:
                    blame = repo.blame(file)
                    touched_hash = []
                    for blame_hunk in blame:
                        for _ in range(blame_hunk.lines_in_hunk):
                            touched_hash.append(str(blame_hunk.final_commit_id))

                    file_row = File(
                        project_id=project.id,
                        commit_hash=str(head_commit.id),
                        path=file,
                        line_touched_hashes=touched_hash
                    )
                    self.__session.merge(file_row)
                self.__session.commit()

                # Repeat for the parent commit
                self._checkout_commit(repo, parent_commit)
        os.chdir(str(cwd))

    def _checkout_commit(self, repo: pygit2.Repository, commit):
        repo.create_reference(DataExtractor.WORKING_TAG_REFNAME, commit.id)
        repo.checkout(DataExtractor.WORKING_TAG_REFNAME)
        repo.lookup_reference(DataExtractor.WORKING_TAG_REFNAME).delete()

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

#    for instance in tests:
#        print(instance.loc, instance.run_time)
#        project = session.query(Project).filter(Project.id == instance.project_id).one()


if __name__ == '__main__':
    main()
