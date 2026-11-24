//go:build !windows

package service

import (
	"fmt"
	"os"
	"syscall"
)

func acquireLock(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("another process owns this state: %w", err)
	}
	return f, nil
}
func releaseLock(f *os.File) error {
	e := syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	c := f.Close()
	if e != nil {
		return e
	}
	return c
}
func syncDirectory(path string) error {
	f, e := os.Open(path)
	if e != nil {
		return e
	}
	defer f.Close()
	return f.Sync()
}
