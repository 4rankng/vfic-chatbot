import { cleanup, render } from "vitest-browser-react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Alert } from "./alert"
import { Badge } from "./badge"
import { Button } from "./button"
import { Card } from "./card"
import { Checkbox } from "./checkbox"
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "./dialog"
import { Input } from "./input"
import { PaginationContent, PaginationLink } from "./pagination"
import { RadioGroup, RadioGroupItem } from "./radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger } from "./select"
import { Skeleton } from "./skeleton"
import { Spinner } from "./spinner"
import { Switch } from "./switch"
import { Table } from "./table"
import { Tabs, TabsList, TabsTrigger } from "./tabs"
import { Textarea } from "./textarea"

afterEach(async () => {
  await cleanup()
})

describe("daisyUI shared adapters", () => {
  it("maps the common visual primitives onto prefixed daisyUI components", async () => {
    const screen = await render(
      <div>
        <Button>Tiếp tục</Button>
        <Button variant="outline">Xem lại</Button>
        <Input aria-label="Tên" />
        <Textarea aria-label="Ghi chú" />
        <Badge>Đang xử lý</Badge>
        <Alert>Không thể đồng bộ dữ liệu.</Alert>
        <Card>Nội dung</Card>
        <Skeleton data-testid="skeleton" />
        <Spinner />
        <Table>
          <tbody>
            <tr>
              <td>Ứng viên</td>
            </tr>
          </tbody>
        </Table>
      </div>
    )

    await expect
      .element(screen.getByRole("button", { name: "Tiếp tục" }))
      .toHaveClass("tt-btn-primary")
    await expect
      .element(screen.getByRole("button", { name: "Tiếp tục" }))
      .toHaveClass("text-[var(--color-primary-content)]!")
    await expect
      .element(screen.getByRole("button", { name: "Tiếp tục" }))
      .not.toHaveClass("text-primary-foreground")
    await expect
      .element(screen.getByRole("button", { name: "Xem lại" }))
      .toHaveClass("tt-btn-outline")
    await expect
      .element(screen.getByRole("textbox", { name: "Tên" }))
      .toHaveClass("tt-input")
    await expect
      .element(screen.getByRole("textbox", { name: "Ghi chú" }))
      .toHaveClass("tt-textarea")
    expect(screen.container.querySelector(".tt-badge")).not.toBeNull()
    await expect.element(screen.getByRole("alert")).toHaveClass("tt-alert")
    expect(screen.container.querySelector(".tt-card")).not.toBeNull()
    expect(screen.container.querySelector(".tt-skeleton")).not.toBeNull()
    expect(screen.container.querySelector(".tt-loading-spinner")).not.toBeNull()
    expect(screen.container.querySelector("table.tt-table")).not.toBeNull()
  })

  it("adopts daisyUI selection controls with native switch markup", async () => {
    const screen = await render(
      <div>
        <Checkbox aria-label="Chọn dòng" />
        <Switch aria-label="Bật Agent" />
        <RadioGroup aria-label="Kênh" defaultValue="zalo">
          <RadioGroupItem value="zalo" aria-label="Zalo" />
        </RadioGroup>
        <Select defaultValue="new">
          <SelectTrigger aria-label="Trạng thái" />
          <SelectContent>
            <SelectItem value="new">Mới</SelectItem>
          </SelectContent>
        </Select>
      </div>
    )

    const checkbox = screen.getByRole("checkbox", { name: "Chọn dòng" })
    const toggle = screen.getByRole("switch", { name: "Bật Agent" })
    const radio = screen.getByRole("radio", { name: "Zalo" })

    await expect.element(checkbox).toHaveClass("tt-checkbox")
    await expect.element(toggle).toHaveClass("tt-toggle")
    await expect.element(toggle).toHaveClass("[--border:1px]")
    expect(toggle.element().tagName).toBe("INPUT")
    await expect.element(toggle).toHaveAttribute("type", "checkbox")
    await expect.element(radio).toHaveClass("tt-radio")
    await expect
      .element(screen.getByRole("combobox", { name: "Trạng thái" }))
      .toHaveClass("tt-select")

    await checkbox.click()
    await toggle.click()
    await radio.click()

    await expect.element(checkbox).toHaveAttribute("aria-checked", "true")
    expect((toggle.element() as HTMLInputElement).checked).toBe(true)
    await expect.element(radio).toHaveAttribute("aria-checked", "true")
  })

  it("preserves native controlled and form-reset switch behavior", async () => {
    const onCheckedChange = vi.fn()
    const onChange = vi.fn()
    const controlledScreen = await render(
      <Switch
        aria-label="Chế độ kiểm soát"
        checked={false}
        onChange={onChange}
        onCheckedChange={onCheckedChange}
      />
    )
    const controlledSwitch = controlledScreen.getByRole("switch", {
      name: "Chế độ kiểm soát",
    })

    await controlledSwitch.click()

    expect(onCheckedChange).toHaveBeenCalledWith(true)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect((controlledSwitch.element() as HTMLInputElement).checked).toBe(false)

    await cleanup()
    const nativeScreen = await render(
      <form>
        <Switch
          aria-label="Nhận thông báo"
          name="notifications"
          defaultChecked
        />
        <Switch aria-label="Không thể thay đổi" disabled />
        <button type="reset">Đặt lại</button>
      </form>
    )
    const nativeSwitch = nativeScreen.getByRole("switch", {
      name: "Nhận thông báo",
    })
    const disabledSwitch = nativeScreen.getByRole("switch", {
      name: "Không thể thay đổi",
    })

    expect((nativeSwitch.element() as HTMLInputElement).checked).toBe(true)
    expect((nativeSwitch.element() as HTMLInputElement).name).toBe(
      "notifications"
    )
    await nativeSwitch.click()
    expect((nativeSwitch.element() as HTMLInputElement).checked).toBe(false)
    await nativeScreen.getByRole("button", { name: "Đặt lại" }).click()
    expect((nativeSwitch.element() as HTMLInputElement).checked).toBe(true)
    expect((disabledSwitch.element() as HTMLInputElement).disabled).toBe(true)
  })

  it("adapts compound navigation and overlay primitives", async () => {
    const screen = await render(
      <div>
        <PaginationContent>
          <li>
            <PaginationLink href="#page-2">2</PaginationLink>
          </li>
        </PaginationContent>
        <Tabs defaultValue="queue">
          <TabsList>
            <TabsTrigger value="queue">Hàng đợi</TabsTrigger>
          </TabsList>
        </Tabs>
        <Dialog>
          <DialogTrigger>Mở hộp thoại</DialogTrigger>
          <DialogContent>
            <DialogTitle>Chi tiết ứng viên</DialogTitle>
          </DialogContent>
        </Dialog>
      </div>
    )

    expect(screen.container.querySelector(".tt-join")).not.toBeNull()
    expect(screen.container.querySelector(".tt-join-item")).not.toBeNull()
    expect(screen.container.querySelector(".tt-tabs")).not.toBeNull()
    expect(screen.container.querySelector(".tt-tab")).not.toBeNull()

    await screen.getByRole("button", { name: "Mở hộp thoại" }).click()
    await expect.element(screen.getByRole("dialog")).toHaveClass("tt-modal-box")
  })
})
