//go:build windows

package service

import (
	"fmt"
	"golang.org/x/sys/windows"
	"os"
)

func acquireLock(path string) (*os.File, error) {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	var ov windows.Overlapped
	if e = windows.LockFileEx(windows.Handle(f.Fd()), windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &ov); e != nil {
		f.Close()
		return nil, fmt.Errorf("another process owns this state: %w", e)
	}
	return f, nil
}
func releaseLock(f *os.File) error {
	var ov windows.Overlapped
	e := windows.UnlockFileEx(windows.Handle(f.Fd()), 0, 1, 0, &ov)
	c := f.Close()
	if e != nil {
		return e
	}
	return c
}

// File.Sync covers the file data. Windows does not support fsync on directories.
func syncDirectory(string) error { return nil }
