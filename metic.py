from models import *


class CalculateMetric:

    def calculate(self, tests):
        num_fail = 0
        total_area = 0
        total_fail = sum(not test.is_passed for test in tests)
        total_run_time = sum(test.run_time for test in tests)

        for test in tests:
            if test.is_passed is True:
                #area = num_fail * test.run_time
                area = (num_fail / total_fail) * (test.run_time / total_run_time) * 100
            else:
                #area = (((2 * num_fail) + 1) * test.run_time) / 2
                area = (((2 * num_fail) + 1) / total_fail) * (test.run_time / total_run_time) / 2 * 100
                num_fail += 1
            total_area += area

        return total_area


if __name__ == '__main__':
    a = CalculateMetric()
    tests = [
        Test(run_time=5, is_passed=False),
        Test(run_time=70, is_passed=False),
        Test(run_time=10, is_passed=True),
        Test(run_time=5, is_passed=True),
        Test(run_time=10, is_passed=True)
    ]

    print("The percentage of the area: ", a.calculate(tests),"%")
