import "@testing-library/react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function Hello(): React.ReactElement {
  return <p>سلام مارجین‌پایلوت</p>;
}

describe("matrix smoke", () => {
  it("renders RTL Persian text", () => {
    render(<Hello />);
    expect(screen.getByText("سلام مارجین‌پایلوت")).toBeTruthy();
  });
});
