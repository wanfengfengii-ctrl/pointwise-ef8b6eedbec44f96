import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 1


class StorageFailure(RuntimeError):
    pass


class Database:
    def __init__(self, path=':memory:'):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute('PRAGMA foreign_keys = ON')
        self.connection.row_factory = sqlite3.Row
        self._faults = {}
        self.closed = False
        self.initialize()

    def initialize(self):
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            self.close()
            raise StorageFailure(f'unsupported database version: {version}')
        self.connection.executescript("""
        BEGIN;
        CREATE TABLE IF NOT EXISTS batches(
            batch_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            canonical TEXT NOT NULL, record_count INTEGER NOT NULL CHECK(record_count>=0),
            receipt TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS records(
            batch_id TEXT NOT NULL REFERENCES batches(batch_id),
            record_index INTEGER NOT NULL CHECK(record_index>=0), payload TEXT NOT NULL,
            PRIMARY KEY(batch_id, record_index));
        CREATE TABLE IF NOT EXISTS plans(
            revision TEXT PRIMARY KEY, name TEXT NOT NULL, definition TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(
            run_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
            plan_revision TEXT NOT NULL REFERENCES plans(revision),
            state TEXT NOT NULL CHECK(state IN ('CREATED','RUNNING','SUCCEEDED','FAILED')),
            row_count INTEGER, error TEXT);
        CREATE TABLE IF NOT EXISTS staging(
            run_id TEXT NOT NULL REFERENCES runs(run_id), output_index INTEGER NOT NULL,
            coordinate TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,output_index));
        CREATE TABLE IF NOT EXISTS results(
            run_id TEXT NOT NULL REFERENCES runs(run_id), output_index INTEGER NOT NULL,
            coordinate TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,output_index));
        PRAGMA user_version = 1;
        COMMIT;
        """)

    def execute(self, sql, parameters=()):
        if self.closed:
            raise StorageFailure('database is closed')
        try:
            return self.connection.execute(sql, parameters)
        except sqlite3.Error as error:
            raise StorageFailure(str(error)) from error

    def inject_once(self, point, after=0):
        if type(after) is not int or after < 0:
            raise ValueError('after must be a nonnegative integer')
        self._faults[point] = after

    def checkpoint(self, point):
        if point not in self._faults:
            return
        if self._faults[point] > 0:
            self._faults[point] -= 1
            return
        del self._faults[point]
        raise StorageFailure(f'injected storage failure: {point}')

    @contextmanager
    def transaction(self, before_commit=None):
        if self.connection.in_transaction:
            raise StorageFailure('nested transaction is not supported')
        self.execute('BEGIN IMMEDIATE')
        try:
            yield
            if before_commit:
                self.checkpoint(before_commit)
            self.execute('COMMIT')
        except BaseException:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise

    def close(self):
        if not self.closed:
            self.connection.close()
            self.closed = True
