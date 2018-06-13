import bisect
import random
from collections import Counter
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy.orm import Session

import data_extract
from models import *


class PrioritizeMethod(Enum):
    BaseRandom = auto()
    BaseLOCInc = auto()
    BaseLOCDesc = auto()
    BaseCoverageInc = auto()
    BaseCoverageDesc = auto()
    LatestCommitRatio = auto()
    LatestCommitCount = auto()
    CommitSinceAverage = auto()
    CommitSinceSum = auto()


class Prioritizer:
    METHOD_MAPPING = None

    def __init__(self, session: Session):
        self._session = session

        self._target_project = None
        self._target_commit = None

        self._data_commits = None
        self._data_files = None
        self._data_tests = None
        self._data_coverages = None
        self._data_diffs = None

        self._covering_hashes = None

        if Prioritizer.METHOD_MAPPING is None:
            Prioritizer.METHOD_MAPPING = {
                PrioritizeMethod.BaseRandom: Prioritizer.by_random,
                PrioritizeMethod.BaseLOCInc: partial(Prioritizer.by_loc, desc=False),
                PrioritizeMethod.BaseLOCDesc: partial(Prioritizer.by_loc, desc=True),
                PrioritizeMethod.BaseCoverageInc: partial(Prioritizer.by_coverage, desc=False),
                PrioritizeMethod.BaseCoverageDesc: partial(Prioritizer.by_coverage, desc=True),
                PrioritizeMethod.LatestCommitRatio: Prioritizer.by_latest_commit_count,
                PrioritizeMethod.LatestCommitCount: Prioritizer.by_latest_commit_ratio,
            }

    @property
    def target_project(self):
        return self._target_project

    @target_project.setter
    def target_project(self, value: Project):
        self._target_project = value

        commits = self._session.query(Commit).filter_by(project_id=value.id).all()
        self._data_commits = {commit.hash: commit for commit in commits}

        self._data_files = None
        self._data_tests = None
        self._data_coverages = None
        self._data_diffs = None
        self._covering_hashes = None

    @property
    def target_commit(self):
        return self._target_commit

    @target_commit.setter
    def target_commit(self, value: Commit) -> bool:
        self._target_commit = value

        files = self._session.query(File).filter_by(
            project_id=self._target_project.id,
            commit_hash=self._target_commit.parent
        )
        self._data_files = {file.path: file for file in files}

        tests = self._session.query(Test).filter_by(
            project_id=self._target_project.id,
            commit_hash=self._target_commit.parent
        )

        self._data_tests = {test.path: test for test in tests}

        diffs = self._session.query(Diff).filter_by(
            project_id=self._target_project.id,
            commit_hash=self._target_commit
        )

        self._data_diffs = {diff.path: diff for diff in diffs}

        self._data_coverages = {}

        for test_path in self._data_tests.keys():
            coverages = self._session.query(Coverage).filter_by(
                project_id=self._target_project.id,
                commit_hash=self._target_commit.parent,
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

    def by_loc(self, desc=False) -> List[Test]:
        multiplier = -1 if desc else 1
        return sorted(
            self._data_tests.values(),
            key=lambda x: (x.loc * multiplier, x.run_time)
        )

    def by_coverage(self, desc=False) -> List[Test]:
        multiplier = -1 if desc else 1
        return sorted(
            self._data_tests.values(),
            key=lambda x: (self._get_covered_loc(x) * multiplier, x.run_time)
        )

    def by_latest_commit_count(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: (self._get_latest_commit_count(x), x.run_time)
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
            diff_hulks = self._data_diffs[file_name].hulks

            coverage = self._data_coverages[test_path][file_name]
            covered_line = coverage.lines_covered
            file_hashes = file.line_touched_hashes[:]
            file_length = len(file.line_touched_hashes)

            for hulk in diff_hulks:
                old_start, old_lines, new_start, new_lines = hulk

                if old_lines == 0 and new_lines > 0:  # added
                    prev_covered = self._has_value(covered_line, new_start - 1) if new_start > 1 else True
                    next_covered = self._has_value(covered_line, new_start) if new_start <= file_length else True

                    if prev_covered and next_covered:
                        covering_hashes.update([self._target_commit.hash] * new_lines)
                else:  # deleted or modified
                    file_hashes[old_start:old_lines] = self._target_commit.hash

            file_hashes = [covered_line[line] for line in file.line_touched_hashes]
            covering_hashes.update(file_hashes)

        return covering_hashes

    def _get_latest_commit_count(self, test: Test) -> int:
        return self._covering_hashes[test.path][self._target_commit.hash]

    def _get_covered_loc(self, test: Test) -> int:
        return sum(
            len(coverage.lines_covered)
            for coverage in self._data_coverages[test.path].values()
        )

    def _get_commit_time_diff(self, commit: Commit) -> int:
        latest_commit = self._data_commits[self._target_commit.hash]

        return latest_commit.timestamp - commit.timestamp

    def _has_value(self, list: List, value: Any):
        return list[bisect.bisect_left(list, value)] == value
