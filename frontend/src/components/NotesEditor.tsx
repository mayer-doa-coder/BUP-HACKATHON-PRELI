import { MAX_OPERATOR_NOTES, MIN_OPERATOR_NOTES } from "../api/types";

interface Props {
  notes: string[];
  onChange: (notes: string[]) => void;
}

/** Editor for the 1–3 free-text operator notes the LLM interpreter will read. */
export function NotesEditor({ notes, onChange }: Props) {
  const updateNote = (index: number, value: string) => {
    const next = [...notes];
    next[index] = value;
    onChange(next);
  };

  const addNote = () => {
    if (notes.length < MAX_OPERATOR_NOTES) onChange([...notes, ""]);
  };

  const removeNote = (index: number) => {
    if (notes.length > MIN_OPERATOR_NOTES) onChange(notes.filter((_, i) => i !== index));
  };

  return (
    <div className="field-group">
      <div className="field-group__header">
        <label>Operator notes</label>
        <span className="field-group__hint">
          {notes.length} / {MAX_OPERATOR_NOTES}
        </span>
      </div>
      {notes.map((note, index) => (
        <div className="note-row" key={index}>
          <textarea
            value={note}
            onChange={(event) => updateNote(index, event.target.value)}
            placeholder={`Note ${index + 1} — e.g. "No discharging between 6 and 9 PM."`}
            rows={2}
          />
          {notes.length > MIN_OPERATOR_NOTES && (
            <button
              type="button"
              className="icon-button"
              onClick={() => removeNote(index)}
              aria-label={`Remove note ${index + 1}`}
              title="Remove note"
            >
              ✕
            </button>
          )}
        </div>
      ))}
      {notes.length < MAX_OPERATOR_NOTES && (
        <button type="button" className="link-button" onClick={addNote}>
          + Add another note
        </button>
      )}
    </div>
  );
}
