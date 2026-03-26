"""External provider integration layer.

Architecture
------------
  providers/        — provider-specific HTTP clients + payload normalization
  status_mapper.py  — translate provider statuses to internal MatchStatus
  sync_service.py   — upsert provider payloads into the internal matches table

The rest of the application never imports from this package directly;
it reads from the internal matches table via MatchService/MatchRepository.
"""
