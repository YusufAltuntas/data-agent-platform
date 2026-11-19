import type { Answer } from "../types";

export function AnswerView({ answer }: { answer: Answer }) {
  return (
    <div className="answer">
      <p className="answer-text">{answer.answer}</p>
      {answer.sql && <AnswerResult answer={answer} />}
    </div>
  );
}

/** The query and its rows; absent when the agent answered without a query. */
function AnswerResult({ answer }: { answer: Answer }) {
  return (
    <>
      <table>
        <thead>
          <tr>
            {answer.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {answer.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell == null ? "" : String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {answer.truncated && <p className="muted">Only the first {answer.rows.length} rows are shown.</p>}
      <h3>SQL</h3>
      <pre>{answer.sql}</pre>
    </>
  );
}
