package server

import (
	"context"
	"time"

	"tide/internal/store"
)

type AlertManager struct{}

func LoadAlerts(path string, st *store.Store) (*AlertManager, error)  { return &AlertManager{}, nil }
func (a *AlertManager) RuleCount() int                                { return 0 }
func (a *AlertManager) Run(ctx context.Context, now func() time.Time) {}
func (a *AlertManager) Snapshot() []any                               { return nil }
