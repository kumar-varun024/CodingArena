import { useEffect, useRef } from 'react';

export function ArtifactDialog({ artifact, fixture, onClose, onDownload }: { artifact: { id: string; text: string }; fixture: boolean; onClose: () => void; onDownload: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="artifact-dialog" aria-labelledby="artifact-title" onClose={onClose} onCancel={onClose}>
    <header><div><span className="eyebrow">{fixture ? 'FIXTURE ARTIFACT' : 'RECORDED ARTIFACT'}</span><h2 id="artifact-title">{artifact.id}</h2></div><button onClick={onClose} aria-label="Close artifact" autoFocus>✕</button></header>
    <pre tabIndex={0}>{artifact.text}</pre><footer><button onClick={onDownload}>Download artifact ↓</button><button onClick={onClose}>Close</button></footer>
  </dialog>;
}
