# Uses W3C Actions API — Appium Python client v3.x removed the old TouchAction API
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction


def tap(driver, x: int, y: int):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(x, y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(0.1)
    actions.w3c_actions.pointer_action.pointer_up()
    actions.perform()


def drag_and_drop(driver, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 500):
    actions = ActionChains(driver)
    actions.w3c_actions = ActionBuilder(driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
    actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pause(duration_ms / 1000)
    actions.w3c_actions.pointer_action.move_to_location(end_x, end_y)
    actions.w3c_actions.pointer_action.pointer_up()
    actions.perform()


def zoom_out_board(driver):
    """Pinch the ZoomAndPanForwardingView scroll view back to full-board zoom.

    XCUITest rule: velocity must be negative when scale < 1 (pinch in = zoom out).
    UIScrollView clamps the resulting zoomScale to minimumZoomScale (1.0 = full view).
    """
    try:
        el = driver.find_element(by='accessibility id',
                                  value='ZoomAndPanForwardingView<Model>.scrollView')
        driver.execute_script('mobile: pinch', {
            'element': el,
            'scale': 0.1,
            'velocity': -2.0,  # negative = fingers moving together (zoom out)
        })
    except Exception:
        driver.execute_script('mobile: pinch', {'scale': 0.1, 'velocity': -2.0})
