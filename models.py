from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, PickleType, Boolean, \
    ForeignKey, Float

Base = declarative_base()


class Project(Base):
    __tablename__ = 'project'

    id = Column(String, primary_key=True)
    git_url = Column(String)


class Commit(Base):
    __tablename__ = 'commit'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    hash = Column(String, primary_key=True)
    parent = Column(String)
    timestamp = Column(Integer)
    count = Column(Integer)  # Recent commit has lower count value


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
    id = Column(String, primary_key=True)

    is_passed = Column(Boolean)
    run_time = Column(Float)
    loc = Column(Integer)

class Coverage(Base):
    __tablename__ = 'coverage'

    project_id = Column(String, ForeignKey(Project.id), primary_key=True)
    commit_hash = Column(String, ForeignKey(Commit.hash), primary_key=True)
    tc_id = Column(String, ForeignKey(Test.id), primary_key=True)
    file_path = Column(String, ForeignKey(File.path), primary_key=True)

    lines_covered = Column(PickleType)
