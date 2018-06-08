import random
import time
from pathlib import Path
from typing import List, Text, Tuple

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pygit2

from models import *


class DataExtractor:
    def __init__(self, db_path: Path):
        engine_url = 'sqlite:///{}'.format(db_path.absolute())
        engine = create_engine(engine_url)

        self.__session = Session(engine)

    def run(self):
        clone_root = Path('cloned_projects')
        clone_root.mkdir(exist_ok=True)

        # 1. Retrieve git project urls
        projects = self.__session.query(Project).all()
        for project in projects:
            project_dir = clone_root / project.id.replace('/', '_')
            # 2. Clone the repository
            try:
                repository = pygit2.clone_repository(project.git_url, str(project_dir))
            except ValueError:
                repository = pygit2.Repository(str(project_dir / '.git'))



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
