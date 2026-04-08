"""Reusable UI button components for ΠThon Arena frontend."""

import os

import pygame


WHITE = (240, 240, 240)
BLUE = (80, 150, 255)

STATE_IDLE = "idle"
STATE_HOVER = "hover"
STATE_PRESSED = "pressed"


#clamps a value between minimum and maximum bounds.
def clamp_value(value, minimum, maximum):
    return max(minimum, min(maximum, value))


#returns the button state based on hover and mouse-press flags.
def get_button_state(is_hovered, is_mouse_down):
    if is_hovered and is_mouse_down:
        return STATE_PRESSED
    if is_hovered:
        return STATE_HOVER
    return STATE_IDLE


#returns current pygame ticks or zero when timing is unavailable.
def get_ticks():
    time_module = getattr(pygame, "time", None)
    if time_module and hasattr(time_module, "get_ticks"):
        return time_module.get_ticks()
    return 0


#returns a brightness-adjusted copy of a pygame surface.
def multiply_brightness(surface, factor):
    factor = clamp_value(factor, 0.0, 3.0)

    tinted = surface.copy()
    if factor == 1.0:
        return tinted

    overlay = pygame.Surface(tinted.get_size(), pygame.SRCALPHA)
    if factor < 1.0:
        amount = clamp_value(int(255 * factor), 0, 255)
        overlay.fill((amount, amount, amount, 255))
        tinted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    else:
        amount = clamp_value(int(255 * (factor - 1.0)), 0, 255)
        overlay.fill((amount, amount, amount, 0))
        tinted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

    return tinted


#loads and scales an image or creates a fallback rectangle surface.
def load_image_or_fallback(path, size, fallback_color):
    if path and os.path.exists(path):
        image = pygame.image.load(path).convert_alpha()
        return pygame.transform.scale(image, size)

    image = pygame.Surface(size, pygame.SRCALPHA)
    image.fill(fallback_color)
    pygame.draw.rect(image, (20, 20, 20), image.get_rect(), 2)
    return image


class UIButton:
    """Simple button that supports idle, hover, and pressed image states."""

    #creates a button with optional image state files and fallback visuals.
    def __init__(self, x, y, width, height, text, font, image_idle_path=None, image_hover_path=None, image_pressed_path=None, base_color=BLUE):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.font = font
        self.base_color = base_color

        self.image_idle = load_image_or_fallback(image_idle_path, (width, height), base_color)

        if image_hover_path:
            self.image_hover = load_image_or_fallback(image_hover_path, (width, height), base_color)
        else:
            self.image_hover = multiply_brightness(self.image_idle, 1.20)

        if image_pressed_path:
            self.image_pressed = load_image_or_fallback(image_pressed_path, (width, height), base_color)
        else:
            self.image_pressed = multiply_brightness(self.image_idle, 0.78)

        self.state = STATE_IDLE
        self.was_down = False
        self.pressed_inside = False
        self.pressed_feedback_until = 0

    #starts a short pressed-state visual feedback window.
    def trigger_press_feedback(self, duration_ms=120):
        self.pressed_feedback_until = max(self.pressed_feedback_until, get_ticks() + duration_ms)

    #updates internal state using mouse position and returns true on click release.
    def update(self, mouse_pos, is_mouse_down):
        hovered = self.rect.collidepoint(mouse_pos)
        self.state = get_button_state(hovered, is_mouse_down)

        if is_mouse_down and not self.was_down:
            self.pressed_inside = hovered

        clicked = False
        if self.was_down and not is_mouse_down and hovered and self.pressed_inside:
            clicked = True

        if not is_mouse_down:
            self.pressed_inside = False

        if get_ticks() < getattr(self, "pressed_feedback_until", 0):
            self.state = STATE_PRESSED

        self.was_down = is_mouse_down
        return clicked

    #draws the button image and centered text label.
    def draw(self, screen):
        if self.state == STATE_PRESSED:
            image = self.image_pressed
        elif self.state == STATE_HOVER:
            image = self.image_hover
        else:
            image = self.image_idle

        screen.blit(image, self.rect.topleft)

        text_surface = self.font.render(self.text, True, WHITE)
        text_rect = text_surface.get_rect(center=self.rect.center)
        screen.blit(text_surface, text_rect)
