import factory

from identity.models import Person


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    username = factory.Faker('user_name')
    email = factory.Faker('safe_email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
