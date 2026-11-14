import { EditorView, keymap, lineNumbers, highlightActiveLine } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { python } from "@codemirror/lang-python";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching } from "@codemirror/language";
import { oneDark } from "@codemirror/theme-one-dark";

window.PyRunnerEditor = {
  mount(parent, initial, onChange) {
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: initial || "",
        extensions: [
          lineNumbers(),
          history(),
          python(),
          bracketMatching(),
          highlightActiveLine(),
          oneDark,
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && onChange) onChange(update.state.doc.toString());
          }),
          EditorView.theme({
            "&": { height: "100%", fontSize: "14px", backgroundColor: "#171a12" },
            ".cm-scroller": {
              overflow: "auto",
              fontFamily: '"Cascadia Code", "Roboto Mono", ui-monospace, monospace',
            },
            ".cm-content": { padding: "12px 0" },
            ".cm-gutters": { backgroundColor: "#12150e", border: "none" },
          }),
        ],
      }),
    });
    return {
      getValue() {
        return view.state.doc.toString();
      },
      setValue(text) {
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: text || "" },
        });
      },
      focus() {
        view.focus();
      },
    };
  },
};
