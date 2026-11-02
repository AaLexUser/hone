/** Prose from the judges uses `backticks` for literals; render those as code and nothing else. */
export function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split('`').map((part, i) =>
        i % 2 ? (
          <code key={i} className="rounded-[4px] bg-ink/6 px-1 font-mono text-[0.92em] text-ink">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  )
}
