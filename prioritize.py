import random
from collections import Counter
from enum import Enum, auto
from typing import List, Dict

from sqlalchemy.orm import Session
from models import *


class PrioritizeMethod(Enum):
    BaseRandom = auto()
    BaseLOC = auto()
    BaseCoverage = auto()
    LatestCommitRatio = auto()
    LatestCommitCount = auto()
    CommitSinceAverage = auto()
    CommitSinceSum = auto()


class Prioritizer:
    METHOD_MAPPING = None

    def __init__(self, session: Session):
        self._session = session
        self._target_project_id = None
        self._target_commit_hash = None

        self._data_project = None
        self._data_commits = None
        self._data_files = None
        self._data_tests = None
        self._data_coverages = None

        self._covering_hashes = None

        if Prioritizer.METHOD_MAPPING is None:
            Prioritizer.METHOD_MAPPING = {
                PrioritizeMethod.BaseRandom: Prioritizer.by_random,
                PrioritizeMethod.BaseLOC: Prioritizer.by_loc,
                PrioritizeMethod.BaseCoverage: Prioritizer.by_coverage,
                PrioritizeMethod.LatestCommitRatio: Prioritizer.by_latest_commit_count,
                PrioritizeMethod.LatestCommitCount: Prioritizer.by_latest_commit_ratio,
            }

    @property
    def target_project(self):
        return self._target_project_id

    @target_project.setter
    def target_project(self, value):
        self._target_project_id = value

        self._data_project = self._session.query(Project).filter_by(id=value).one()

        commits = self._session.query(Commit).filter_by(project_id=value).all()
        self._data_commits = {commit.hash: commit for commit in commits}

        self._target_commit_hash = None
        self._data_files = None
        self._data_tests = None
        self._data_coverages = None
        self._covering_hashes = None

    @property
    def target_commit(self):
        return self._target_commit_hash

    @target_commit.setter
    def target_commit(self, value):
        self._target_commit_hash = value

        files = self._session.query(File).filter_by(
            project_id=self._target_project_id,
            commit_hash=self._target_commit_hash
        )
        self._data_files = {file.path: file for file in files}

        tests = self._session.query(Test).filter_by(
            project_id=self._target_project_id,
            commit_hash=self._target_commit_hash
        )

        self._data_tests = {test.path: test for test in tests}

        self._data_coverages = {}

        for test_path in self._data_tests.keys():
            coverages = self._session.query(Coverage).filter_by(
                project_id=self._target_project_id,
                commit_hash=self._target_commit_hash,
                tc_path=test_path
            ).all()

            self._data_coverages[test_path] = {
                coverage.file_path: coverage
                for coverage in coverages
            }

        self._covering_hashes = {
            self._get_covering_hashes(test_path)
            for test_path in self._data_tests.keys()
        }

    def by_random(self) -> List[Test]:
        return random.shuffle(self._data_tests.values())[:]

    def by_runtime(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: x.run_time
        )

    def by_loc(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: x.loc
        )

    def by_coverage(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=self._get_covered_loc
        )

    def by_latest_commit_count(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=self._get_latest_commit_count
        )

    def by_latest_commit_ratio(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: self._get_latest_commit_count(x) / self._get_covered_loc(x)
        )

    def by_all(self) -> Dict[PrioritizeMethod, List[Test]]:
        return {
            method: func()
            for method, func in Prioritizer.METHOD_MAPPING
        }

    def _get_covering_hashes(self, test_path: str) -> Counter:
        covering_hashes = Counter()
        for file_name, file in self._data_files.items():
            coverage = self._data_coverages[test_path][file_name]
            covered_line = coverage.lines_covered

            file_hashes = [covered_line[line] for line in file.line_touched_hashes]
            covering_hashes.update(file_hashes)

        return covering_hashes

    def _get_latest_commit_count(self, test: Test) -> int:
        return self._covering_hashes[test.path][self._target_commit_hash]

    def _get_covered_loc(self, test: Test) -> int:
        return sum(
            len(coverage.lines_covered)
            for coverage in self._data_coverages[test.path].values()
        )

    def _get_commit_time_diff(self, commit: Commit) -> int:
        latest_commit = self._data_commits[self._target_commit_hash]

        return latest_commit.timestamp - commit.timestamp
