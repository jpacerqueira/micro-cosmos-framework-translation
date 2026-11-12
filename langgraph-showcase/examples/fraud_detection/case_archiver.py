"""Legacy case archiver (Python 2 style).

Wrote closed fraud cases to a flat-file archive. Replaced by the central
case management system — no longer imported by the main pipeline.
"""

import os
import time

_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "case_archive")


class CaseArchiver:

    def __init__(self, case_dir=None):
        self.case_dir = case_dir or _ARCHIVE_DIR

    def archive_case(self, case_id, account_id, decision, score):
        if not os.path.exists(self.case_dir):
            os.makedirs(self.case_dir)
        stamp = time.strftime("%Y%m%d")
        filename = "%s_%s_%s.txt" % (stamp, case_id, decision)
        path = os.path.join(self.case_dir, filename)
        with open(path, "wb") as fh:
            fh.write(
                "case=%s account=%s decision=%s score=%.4f ts=%s\n" % (
                    case_id, account_id, decision, float(score),
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
            )
        print "Archived case %s to %s" % (case_id, path)

    def list_cases(self, date_prefix=None):
        if not os.path.exists(self.case_dir):
            return []
        files = os.listdir(self.case_dir)
        if date_prefix:
            files = [f for f in files if f.startswith(date_prefix)]
        return sorted(files)
