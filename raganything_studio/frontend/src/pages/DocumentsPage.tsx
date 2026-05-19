import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertCircle, BarChart3, ChevronDown, ChevronUp, Eye, FilePlus2, Loader2, Play, RefreshCw } from 'lucide-react'
import { getDocuments, processDocument } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { DocumentRecord, DocumentStatus } from '../types/studio'

type StatusFilter = DocumentStatus | 'all'

function docActionLink(doc: DocumentRecord): { to: string; title: string; label: string } | null {
  if (doc.status === 'processing') {
    return doc.latest_job_id ? { to: `/jobs/${doc.latest_job_id}`, title: 'View job progress', label: 'Job' } : null
  }
  if (doc.status === 'failed') {
    return doc.latest_job_id ? { to: `/jobs/${doc.latest_job_id}`, title: 'View error details', label: 'Job' } : null
  }
  if (doc.status === 'indexed' || doc.result_available) {
    return { to: `/documents/${doc.id}/result`, title: 'View processing result', label: 'Result' }
  }
  return null
}

export default function DocumentsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [showPipeline, setShowPipeline] = useState(false)
  const { data: documents = [], isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['documents'],
    queryFn: getDocuments,
    refetchInterval: (query) => {
      const hasActive = (query.state.data ?? []).some((d) => d.status === 'processing')
      return hasActive ? 2000 : false
    },
  })
  const retryMutation = useMutation({
    mutationFn: (documentId: string) => processDocument(documentId, {}),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      navigate(`/jobs/${response.job_id}`)
    },
  })
  const counts = useMemo(() => countDocuments(documents), [documents])
  const activeJobs = useMemo(() => documents.filter((d) => d.status === 'processing'), [documents])
  const recentFailed = useMemo(() => documents.filter((d) => d.status === 'failed'), [documents])
  const filteredDocuments = statusFilter === 'all'
    ? documents
    : documents.filter((doc) => doc.status === statusFilter)

  return (
    <section className="documents-workspace">
      <div className="documents-card">
        <div className="documents-card-header">
          <h1>Documents</h1>
        </div>

        <div className="documents-toolbar">
          <div className="documents-toolbar-group">
            <button className="button" type="button" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw size={16} className={isFetching ? 'spin' : ''} />
              Scan
            </button>
            <button
              className={`button${showPipeline ? ' active' : ''}`}
              type="button"
              onClick={() => setShowPipeline((v) => !v)}
            >
              <Activity size={16} />
              Pipeline Status
              {activeJobs.length > 0 ? <span className="toolbar-badge">{activeJobs.length}</span> : null}
              {showPipeline ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
          <div className="documents-toolbar-group">
            <Link className="button primary" to="/documents/new">
              <FilePlus2 size={16} />
              Upload
            </Link>
          </div>
        </div>

        {showPipeline ? (
          <PipelineStatusPanel activeJobs={activeJobs} recentFailed={recentFailed} />
        ) : null}

        <div className="documents-inner-card">
          <div className="documents-inner-header">
            <h2>Uploaded Documents</h2>
            <div className="status-filter-row">
              <StatusFilterButton active={statusFilter === 'all'} label="All" count={counts.all} onClick={() => setStatusFilter('all')} />
              <StatusFilterButton active={statusFilter === 'indexed'} label="Completed" count={counts.indexed} tone="green" onClick={() => setStatusFilter('indexed')} />
              <StatusFilterButton active={statusFilter === 'processing'} label="Processing" count={counts.processing} tone="blue" onClick={() => setStatusFilter('processing')} />
              <StatusFilterButton active={statusFilter === 'uploaded'} label="Pending" count={counts.uploaded} tone="yellow" onClick={() => setStatusFilter('uploaded')} />
              <StatusFilterButton active={statusFilter === 'failed'} label="Failed" count={counts.failed} tone="red" onClick={() => setStatusFilter('failed')} />
            </div>
          </div>

          {error ? <div className="error-panel">{(error as Error).message}</div> : null}
          {isLoading ? <div className="empty">Loading documents</div> : null}

          <div className="documents-table-wrap">
            <div className="table documents-table">
              <div className="table-row documents-table-row table-head">
                <span>File Name</span>
                <span>Summary</span>
                <span>Status</span>
                <span>Length</span>
                <span>Chunks</span>
                <span>Created</span>
                <span>Updated</span>
                <span></span>
              </div>
              {filteredDocuments.map((doc) => {
                const action = docActionLink(doc)
                return (
                  <div className="table-row documents-table-row" key={doc.id}>
                    <span className="doc-name">
                      <strong>{doc.filename}</strong>
                      <small>{doc.id}</small>
                    </span>
                    <DocumentDetail doc={doc} />
                    <span className="doc-status-cell">
                      <StatusBadge status={doc.status} />
                      {doc.status === 'processing' ? <Loader2 size={13} className="spin doc-spin" /> : null}
                    </span>
                    <span>{doc.content_items_count ?? '-'}</span>
                    <span>{doc.chunks_count ?? '-'}</span>
                    <span>{new Date(doc.created_at).toLocaleString()}</span>
                    <span>{new Date(doc.updated_at).toLocaleString()}</span>
                    <span className="doc-actions">
                    {(doc.status === 'failed' || doc.status === 'uploaded') ? (
                      <button
                        className="icon-button doc-action-button"
                        type="button"
                        title={doc.status === 'failed' ? 'Retry processing' : 'Start processing'}
                        disabled={retryMutation.isPending}
                        onClick={() => retryMutation.mutate(doc.id)}
                      >
                        <Play size={16} />
                      </button>
                    ) : null}
                    {action ? (
                      <Link className="icon-button doc-action-button" to={action.to} title={action.title}>
                        <Eye size={16} />
                      </Link>
                    ) : null}
                  </span>
                  </div>
                )
              })}
            </div>
            {!isLoading && filteredDocuments.length === 0 ? (
              <div className="empty documents-empty">No documents in this status</div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  )
}

function StatusFilterButton({
  active, label, count, tone = 'neutral', onClick,
}: {
  active: boolean
  label: string
  count: number
  tone?: 'neutral' | 'green' | 'blue' | 'yellow' | 'red'
  onClick: () => void
}) {
  return (
    <button
      className={`status-filter status-filter--${tone} ${active ? 'active' : ''}`}
      onClick={onClick}
      type="button"
    >
      {label} ({count})
    </button>
  )
}

function countDocuments(documents: DocumentRecord[]) {
  return documents.reduce(
    (counts, doc) => ({
      ...counts,
      all: counts.all + 1,
      [doc.status]: counts[doc.status] + 1,
    }),
    {
      all: 0,
      uploaded: 0,
      processing: 0,
      indexed: 0,
      failed: 0,
    } satisfies Record<StatusFilter, number>,
  )
}

function DocumentDetail({ doc }: { doc: DocumentRecord }) {
  if (doc.status === 'processing') {
    const progress = Math.round((doc.latest_job_progress ?? 0) * 100)
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">
          <BarChart3 size={13} />
          {doc.latest_job_stage ?? 'processing'} · {progress}%
        </span>
        <span className="doc-mini-progress"><span style={{ width: `${progress}%` }} /></span>
      </span>
    )
  }

  if (doc.status === 'indexed') {
    const chunks = doc.chunks_count != null ? `${doc.chunks_count} chunks` : null
    const items = doc.content_items_count != null ? `${doc.content_items_count} result items` : null
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">{[chunks, items].filter(Boolean).join(' · ') || 'Ready'}</span>
        <small>{doc.status_detail ?? 'Processing result available'}</small>
      </span>
    )
  }

  if (doc.result_available) {
    return (
      <span className="doc-detail">
        <span className="doc-detail__line">{doc.content_items_count ?? 0} result items</span>
        <small>{doc.status_detail ?? 'Parser result available'}</small>
      </span>
    )
  }

  if (doc.status === 'failed') {
    return (
      <span className="doc-detail doc-detail--failed">
        <span className="doc-detail__line"><AlertCircle size={13} /> Failed</span>
        <small>{doc.status_detail ?? doc.error ?? 'Open job details for traceback'}</small>
      </span>
    )
  }

  return (
    <span className="doc-detail">
      <span className="doc-detail__line">Not processed</span>
      <small>{doc.status_detail ?? 'Upload complete; processing has not started'}</small>
    </span>
  )
}

function PipelineStatusPanel({
  activeJobs,
  recentFailed,
}: {
  activeJobs: DocumentRecord[]
  recentFailed: DocumentRecord[]
}) {
  return (
    <div className="pipeline-status-panel">
      <div className="pipeline-section">
        <h3>Active Processing ({activeJobs.length})</h3>
        {activeJobs.length === 0 ? (
          <p className="pipeline-empty">No documents currently processing</p>
        ) : (
          <div className="pipeline-jobs">
            {activeJobs.map((doc) => {
              const progress = Math.round((doc.latest_job_progress ?? 0) * 100)
              return (
                <div className="pipeline-job" key={doc.id}>
                  <div className="pipeline-job-header">
                    <strong>{doc.filename}</strong>
                    <span className="pipeline-job-stage">{doc.latest_job_stage ?? 'processing'}</span>
                  </div>
                  <div className="pipeline-job-bar">
                    <div className="pipeline-job-fill" style={{ width: `${progress}%` }} />
                  </div>
                  <div className="pipeline-job-footer">
                    <small>{doc.latest_job_message ?? `${progress}% complete`}</small>
                    {doc.latest_job_id ? (
                      <Link className="pipeline-job-link" to={`/jobs/${doc.latest_job_id}`}>View job</Link>
                    ) : null}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {recentFailed.length > 0 ? (
        <div className="pipeline-section pipeline-section--failed">
          <h3>Failed ({recentFailed.length})</h3>
          <div className="pipeline-jobs">
            {recentFailed.map((doc) => (
              <div className="pipeline-job pipeline-job--failed" key={doc.id}>
                <div className="pipeline-job-header">
                  <strong>{doc.filename}</strong>
                  <AlertCircle size={14} />
                </div>
                <small>{doc.status_detail ?? doc.error ?? 'Unknown error'}</small>
                {doc.latest_job_id ? (
                  <Link className="pipeline-job-link" to={`/jobs/${doc.latest_job_id}`}>View error</Link>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
