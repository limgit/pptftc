from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, PickleType, Boolean, ForeignKey


Base = declarative_base()


class Project(Base):
    __tablename__ = 'project'

    id = Column(String, primary_key=True)
    git_url = Column(String)


class Commit(Base):
    __tablename__ = 'commit'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    hash = Column(String, primary_key=True)
    timestamp = Column(DateTime)
    added_loc = Column(Integer)
    deleted_loc = Column(Integer)


class File(Base):
    __tablename__ = 'file'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    commit_hash = Column(String, ForeignKey(Commit.hash), primary_key=True)
    path = Column(String, primary_key=True)
    line_touched_hashes = Column(PickleType)


class Test(Base):
    __tablename__ = 'test'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    commit_hash = Column(String, ForeignKey(Commit.hash), primary_key=True)
    path = Column(String, primary_key=True)

    is_passed = Column(Boolean)
    run_time = Column(Integer)


class Coverage(Base):
    __tablename__ = 'coverage'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    commit_hash = Column(String, ForeignKey(Commit.hash), primary_key=True)
    tc_path = Column(String, ForeignKey(Test.path), primary_key=True)
    file_path = Column(String, ForeignKey(File.path), primary_key=True)

    lines_covered = Column(PickleType)
    run_time = Column(Integer)
