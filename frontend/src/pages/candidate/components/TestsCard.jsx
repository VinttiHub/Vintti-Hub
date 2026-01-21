import { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { deleteCandidateTest, fetchCandidateTests, uploadCandidateTests } from '../../../services/candidateDetailService.js';

function TestsCard({ candidateId }) {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  const items = useMemo(() => normalizeItems(documents), [documents]);

  const loadDocuments = useCallback(async () => {
    if (!candidateId) {
      setDocuments([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const list = await fetchCandidateTests(candidateId);
      setDocuments(list);
    } catch (err) {
      console.error('Failed to load candidate tests', err);
      setError('Unable to load files right now.');
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleUpload = useCallback(async (event) => {
    if (!candidateId) return;
    const fileList = Array.from(event.target.files || []);
    event.target.value = '';
    if (!fileList.length) return;
    setUploading(true);
    setError('');
    try {
      const formData = new FormData();
      fileList.forEach((file) => formData.append('files', file));
      const response = await uploadCandidateTests(candidateId, formData);
      setDocuments(response?.items || response || []);
    } catch (err) {
      console.error('Failed to upload tests', err);
      setError(err?.message || 'Unable to upload files.');
    } finally {
      setUploading(false);
    }
  }, [candidateId]);

  const handleRemove = useCallback(async (key) => {
    if (!candidateId || !key) return;
    if (!window.confirm('Remove this file?')) return;
    setError('');
    try {
      const response = await deleteCandidateTest(candidateId, key);
      setDocuments(response?.items || response || []);
    } catch (err) {
      console.error('Failed to delete test file', err);
      setError(err?.message || 'Unable to delete file.');
    }
  }, [candidateId]);

  return (
    <section className="tests-card" aria-label="Tests and supporting files">
      <div className="tests-card-header">
        <div>
          <h3>Tests</h3>
          <p>Upload assessments, certifications or any files shared by the candidate.</p>
        </div>
        <label className={`tests-upload-button ${uploading ? 'is-disabled' : ''}`}>
          <input
            type="file"
            multiple
            onChange={handleUpload}
            disabled={uploading}
            aria-label="Upload candidate tests"
          />
          {uploading ? 'Uploading…' : 'Upload files'}
        </label>
      </div>

      {error && <p className="tests-error">{error}</p>}

      {loading ? (
        <p className="tests-placeholder">Loading files…</p>
      ) : items.length === 0 ? (
        <p className="tests-placeholder">No files uploaded yet.</p>
      ) : (
        <ul className="tests-file-list">
          {items.map((file) => (
            <li key={file.key} className="tests-file-row">
              <div className="tests-file-meta">
                <a href={file.url} target="_blank" rel="noopener noreferrer">
                  {file.name}
                </a>
                {file.uploaded_at && (
                  <span className="tests-file-note">
                    Uploaded {formatDateLabel(file.uploaded_at)}
                  </span>
                )}
              </div>
              <div className="tests-file-actions">
                <button type="button" className="tests-remove-button" onClick={() => handleRemove(file.key)}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function normalizeItems(value) {
  if (Array.isArray(value)) return value;
  if (value?.items && Array.isArray(value.items)) return value.items;
  return [];
}

function formatDateLabel(date) {
  if (!date) return '';
  try {
    const parsed = new Date(date);
    if (Number.isNaN(parsed.getTime())) return '';
    return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return '';
  }
}

TestsCard.propTypes = {
  candidateId: PropTypes.number,
};

export default TestsCard;
