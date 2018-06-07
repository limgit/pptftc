import random
import time
from pathlib import Path
from typing import List, Text, Tuple

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import *


def prepare_session(path: Path) -> Session:
    engine_url = 'sqlite:///{}'.format(path.absolute())
    engine = create_engine(engine_url)
    session = Session(engine)

    Base.metadata.create_all(engine)

    return session


def load_projects(path: Path) -> List[Tuple[Text, Text]]:
    return [Project(**{'id': line.rsplit('/')[-1].strip(), 'git_url': line})
            for line in path.read_text().split() if line]


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

    tests = session.query(Test).all()

    random_order = random.shuffle(tests)
    runtime_order = session.query(Test).order_by(Test.run_time).all()
    loc_order = session.query(Test).order_by(Test.loc).all()

#    for instance in tests:
#        print(instance.loc, instance.run_time)
#        project = session.query(Project).filter(Project.id == instance.project_id).one()

if __name__ == '__main__':
    main()
