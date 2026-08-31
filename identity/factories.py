import factory

from identity.models import Person


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    name = factory.Faker('name')
    email = factory.Sequence(lambda n: f'person{n}@example.com')
    is_admin = False

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """
        Set the instance password or mark it as unusable.
        
        Parameters:
            create (bool): Whether to save the instance after setting its password.
            extracted (str | None): Password to assign to the instance.
        """
        if extracted:
            self.set_password(extracted)
        else:
            self.set_unusable_password()
        if create:
            self.save()
