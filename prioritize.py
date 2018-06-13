import bisect
import random
from collections import Counter
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from sqlalchemy.orm import Session

import data_extract
from metic import CalculateMetric
from models import *


class PrioritizeMethod(Enum):
    BaseRandom = auto()
    BaseLOCInc = auto()
    BaseLOCDesc = auto()
    BaseCoverageInc = auto()
    BaseCoverageDesc = auto()
    BaseRuntimeInc = auto()
    BaseRuntimeDesc = auto()
    LatestCommitRatio = auto()
    LatestCommitCount = auto()
    CommitAheadAverage = auto()
    CommitAheadSum = auto()


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
                PrioritizeMethod.BaseRandom: self.by_random,
                PrioritizeMethod.BaseLOCInc: partial(self.by_loc, desc=False),
                PrioritizeMethod.BaseLOCDesc: partial(self.by_loc, desc=True),
                PrioritizeMethod.BaseCoverageInc: partial(self.by_coverage, desc=False),
                PrioritizeMethod.BaseCoverageDesc: partial(self.by_coverage, desc=True),
                PrioritizeMethod.BaseRuntimeInc: partial(self.by_run_time, desc=False),
                PrioritizeMethod.BaseRuntimeDesc: partial(self.by_run_time, desc=True),
                PrioritizeMethod.LatestCommitRatio: self.by_latest_commit_count,
                PrioritizeMethod.LatestCommitCount: self.by_latest_commit_ratio,
                PrioritizeMethod.CommitAheadAverage: self.by_commit_ahead_average,
                PrioritizeMethod.CommitAheadSum: self.by_commit_ahead_sum,
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

        self._data_tests = {test.id: test for test in tests}

        diffs = self._session.query(Diff).filter_by(
            project_id=self._target_project.id,
            commit_hash=self._target_commit.hash
        )

        self._data_diffs = {diff.path: diff for diff in diffs}

        self._data_coverages = {}

        for test_id in self._data_tests.keys():
            coverages = self._session.query(Coverage).filter_by(
                project_id=self._target_project.id,
                commit_hash=self._target_commit.parent,
                tc_id=test_id
            ).all()

            self._data_coverages[test_id] = {
                coverage.file_path: coverage
                for coverage in coverages
            }

        self._covering_hashes = {
            test_id: self._get_covering_hashes(test_id)
            for test_id in self._data_tests.keys()
        }

    @property
    def has_failed_test(self):
        return any(not test.is_passed for test in self._data_tests.values())

    def by_random(self) -> List[Test]:
        tests = list(self._data_tests.values())
        random.shuffle(tests)

        return tests

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

    def by_run_time(self, desc=False) -> List[Test]:
        multiplier = -1 if desc else 1
        return sorted(
            self._data_tests.values(),
            key=lambda x: x.run_time * multiplier
        )

    def by_latest_commit_count(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: (-self._get_latest_commit_count(x), x.run_time)
        )

    def by_latest_commit_ratio(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: -(self._get_latest_commit_count(x) / self._get_covered_loc(x))
        )

    def by_commit_ahead_sum(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: (self._get_ahead_count(x), x.run_time)
        )

    def by_commit_ahead_average(self) -> List[Test]:
        return sorted(
            self._data_tests.values(),
            key=lambda x: self._get_ahead_count(x) / self._get_covered_loc(x),
        )

    def by_all(self) -> Dict[PrioritizeMethod, List[Test]]:
        return {
            method: func()
            for method, func in Prioritizer.METHOD_MAPPING.items()
        }

    def get_raw_values(self) -> Dict[PrioritizeMethod, List[Test]]:
        results = {
            PrioritizeMethod.BaseLOCDesc: [],
            PrioritizeMethod.BaseCoverageInc: [],
            PrioritizeMethod.BaseRuntimeInc: [],
            PrioritizeMethod.LatestCommitCount: [],
            PrioritizeMethod.LatestCommitRatio: [],
            PrioritizeMethod.CommitAheadSum: [],
            PrioritizeMethod.CommitAheadAverage: []
        }

        for test in self._data_tests.values():
            results[PrioritizeMethod.BaseLOCDesc].append(
                test.loc
            )
            results[PrioritizeMethod.BaseCoverageInc].append(
                self._get_covered_loc(test)
            )
            results[PrioritizeMethod.BaseRuntimeInc].append(
                test.run_time
            )
            results[PrioritizeMethod.LatestCommitCount].append(
                self._get_latest_commit_count(test)
            )
            results[PrioritizeMethod.LatestCommitRatio].append(
                self._get_latest_commit_count(test) / self._get_covered_loc(test)
            )
            results[PrioritizeMethod.CommitAheadSum].append(
                self._get_ahead_count(test)
            )
            results[PrioritizeMethod.CommitAheadAverage].append(
                self._get_ahead_count(test) / self._get_covered_loc(test)
            )

        return results

    def _get_covering_hashes(self, test_path: str) -> Counter:
        covering_hashes = Counter()
        for file_name, file in self._data_files.items():
            diff_hunks = self._data_diffs[file_name].hunks if file_name in self._data_diffs else []

            if file_name not in self._data_coverages[test_path]:
                continue

            coverage = self._data_coverages[test_path][file_name]
            covered_line = coverage.lines_covered
            file_hashes = file.line_touched_hashes[:]
            file_length = len(file.line_touched_hashes)

            for hunk in diff_hunks:
                old_start, old_lines, new_start, new_lines = hunk

                if old_lines == 0 and new_lines > 0:  # added
                    prev_covered = self._has_value(covered_line, new_start - 1) if new_start > 1 else True
                    next_covered = self._has_value(covered_line, new_start) if new_start <= file_length else True

                    if prev_covered and next_covered:
                        covering_hashes.update([self._target_commit.hash] * new_lines)
                else:  # deleted or modified
                    file_hashes[old_start:old_lines] = self._target_commit.hash

            file_hashes = [file.line_touched_hashes[line - 1] for line in covered_line]
            covering_hashes.update(file_hashes)

        return covering_hashes

    def _get_latest_commit_count(self, test: Test) -> int:
        return self._covering_hashes[test.id][self._target_commit.hash]

    def _get_ahead_count(self, test: Test) -> int:
        counter = self._covering_hashes[test.id]

        commit_count_list = [
            self._data_commits[hash].count
            for hash in counter
            if hash in self._data_commits
        ]

        min_commit_count = min(commit_count_list) if commit_count_list else 0

        return sum(
            (self._data_commits[hash].count - min_commit_count) * count
            for hash, count in counter.items()
            if hash in self._data_commits
        )

    def _get_covered_loc(self, test: Test) -> int:
        result = sum(len(coverage.lines_covered) for coverage in self._data_coverages[test.id].values())

        return result if result else 1

    def _get_commit_time_diff(self, commit: Commit) -> int:
        latest_commit = self._data_commits[self._target_commit.hash]

        return latest_commit.timestamp - commit.timestamp

    def _has_value(self, list: List, value: Any):
        index = bisect.bisect_left(list, value)
        return list[index] == value if index < len(list) else False


def main():
    session = data_extract.prepare_session(Path('db/db.sqlite'))
    pri = Prioritizer(session)

    projects = session.query(Project).all()
    calc = CalculateMetric()

    results = {
        method: []
        for method in PrioritizeMethod.__members__.values()
    }

    corr = None

    for project in projects:
        commits = session.query(Commit).filter_by(
            project_id=project.id
        ).all()

        pri.target_project = project

        for commit in commits:
            pri.target_commit = commit

            if not pri.has_failed_test:
                continue

            commit_results = pri.by_all()
            commit_corr = pd.DataFrame(pri.get_raw_values())
            if corr is not None:
                corr = pd.concat([corr, commit_corr])
            else:
                corr = commit_corr

            for method, tests in commit_results.items():
                results[method].append(calc.calculate(tests))

    print(len(results[PrioritizeMethod.CommitAheadSum]))
    for method, metrics in results.items():
        print(method, sum(metrics) / len(metrics))

    print(corr.corr())


if __name__ == '__main__':
    main()